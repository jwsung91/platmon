#!/usr/bin/env python3
"""platmon: start the collector core once, then the frontends enabled in the config.

Usage: python3 platmon.py [config.ini] [--frontends http,terminal]
Without a config file the built-in defaults apply (see platmon.ini).
"""
import argparse
import configparser

from collector import collect
from collector.sampler import Sampler
from frontends import server, terminal

FRONTENDS = {"http": server.start, "terminal": terminal.start}  # name -> start(sampler, cfg section)

DEFAULTS = {
    "core": {"interval": "1.0"},
    "http": {"enabled": "yes", "bind": "0.0.0.0", "port": "8080", "web": "yes"},
    "terminal": {"enabled": "no"},
}


def load_config(path=None, frontends=None):
    """Defaults < config file < frontends (list of names; enables exactly those). Raises ValueError."""
    cfg = configparser.ConfigParser()
    cfg.read_dict(DEFAULTS)
    if path and not cfg.read(path):
        raise ValueError(f"cannot read config {path}")
    unknown = set(cfg.sections()) - DEFAULTS.keys()
    if unknown:
        raise ValueError(f"unknown config section(s): {', '.join(sorted(unknown))}")
    if frontends is not None:
        unknown = set(frontends) - FRONTENDS.keys()
        if unknown:
            raise ValueError(f"unknown frontend(s): {', '.join(sorted(unknown))}; choose from {', '.join(FRONTENDS)}")
        for name in FRONTENDS:
            cfg[name]["enabled"] = "yes" if name in frontends else "no"
    return cfg


def main(argv=None):
    p = argparse.ArgumentParser(description="platmon platform monitor")
    p.add_argument("config", nargs="?", help="INI file; built-in defaults apply without one")
    p.add_argument("--frontends", help=f"comma-separated, overrides enabled= in the config ({','.join(FRONTENDS)})")
    a = p.parse_args(argv)
    try:
        cfg = load_config(a.config, a.frontends.split(",") if a.frontends else None)
    except ValueError as e:
        p.error(str(e))

    sampler = Sampler(collect, cfg["core"].getfloat("interval")).start()
    threads = [t for name, start in FRONTENDS.items()
               if cfg[name].getboolean("enabled") and (t := start(sampler, cfg[name]))]
    if not threads:
        p.error("no frontend is running; enable one in the config or with --frontends")
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
