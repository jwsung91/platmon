#!/usr/bin/env python3
"""platmon terminal client: live view of a platmon service, this device's by default.
Standalone (standard library only); scripts/install-cli.sh installs it as the `platmon` command.

Usage: platmon [host[:port]] [interval_sec] [--once]   (default localhost:9797, 1s)
The service itself runs in the background: scripts/systemd/install.sh or scripts/docker/start.sh.
"""
# platmon-cli: marker that lets scripts/install-cli.sh recognise (and only replace) its own command
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

PORT = 9797


def bar(pct, width=20):
    n = round(width * max(0, min(pct, 100)) / 100)
    return "█" * n + "·" * (width - n)


def gib(b):
    return f"{b / 2**30:.1f}G"


SYSTEM_LABELS = {"os": "", "kernel": "kernel ", "arch": "", "hostname": "host ", "l4t": "L4T "}  # others: "key value"


def system_line(system):
    """One line from the system entries, whatever the board added; empty for servers without them."""
    return " · ".join(SYSTEM_LABELS.get(k, f"{k} ") + str(v) for k, v in (system or {}).items() if v)


def render(s):
    up = int(s["uptime"])
    system = system_line(s.get("system"))
    lines = [
        f"{s['model']}",
        f"{s['platform']}   " + (f"mode {s['power_mode']}   " if s["power_mode"] else "") + f"up {up // 86400}d {up % 86400 // 3600:02}:{up % 3600 // 60:02}",
        *([system] if system else []),
        "",
    ]
    for c in s["cpu"]:
        freq = f"  {c['freq'] / 1e6:4.0f} MHz" if c["freq"] else ""
        lines.append(f"CPU{c['id']:<3}{bar(c['usage'])} {c['usage']:5.1f}%{freq}")
    g = s["gpu"]
    if g:
        freq = f"  {g['freq'] / 1e6:4.0f} MHz" if g.get("freq") else ""  # None: clock not readable
        lines.append(f"GPU   {bar(g['usage'])} {g['usage']:5.1f}%{freq}")
    m = s["memory"]
    lines.append(f"RAM   {bar(100 * m['used'] / m['total'])} {gib(m['used'])}/{gib(m['total'])}")
    if m["swap_total"]:
        lines.append(f"SWAP  {bar(100 * m['swap_used'] / m['swap_total'])} {gib(m['swap_used'])}/{gib(m['swap_total'])}")
    d = s["disk"]
    lines.append(f"DISK  {bar(100 * d['used'] / d['total'])} {gib(d['used'])}/{gib(d['total'])}")
    lines.append("")
    if s["temperature"]:
        lines.append("TEMP  " + "  ".join(f"{k} {v:.1f}°C" for k, v in s["temperature"].items()))
    if s["power"]:
        lines.append("POWER " + "  ".join(f"{k} {v:.2f}W" for k, v in s["power"].items()))
    for f in s["fans"]:
        vals = [f"{f['rpm']} rpm" if f["rpm"] is not None else "", f"{f['percent']}%" if f["percent"] is not None else ""]
        lines.append(f"FAN   {f['name']}  " + ("  ".join(v for v in vals if v) or "n/a"))  # n/a: unreadable
    return "\n".join(lines)


def explain(addr, e):
    """Why the service could not be read, and what to do about it."""
    if isinstance(e, urllib.error.HTTPError):
        hint = "\n  it has no current data yet, or collection keeps failing; check the service log" if e.code == 503 else ""
        return f"platmon at {addr} answered {e.code} {e.reason}{hint}"
    reason = getattr(e, "reason", e)
    if addr.rsplit(":", 1)[0] in ("localhost", "127.0.0.1"):
        return (f"platmon is not running on {addr} ({reason})\n"
                "  start the service from the platmon repo: scripts/systemd/install.sh or scripts/docker/start.sh")
    return f"cannot reach platmon at {addr} ({reason})\n  check that its service runs there and the port is reachable"


def main(argv=None):
    p = argparse.ArgumentParser(prog="platmon", description="Live view of a platmon service (this device by default).",
                                epilog="The service runs in the background: scripts/systemd/install.sh or "
                                       "scripts/docker/start.sh in the platmon repo.")
    p.add_argument("host", nargs="?", default="localhost", help=f"host[:port], default localhost:{PORT}")
    p.add_argument("interval", nargs="?", type=float, default=1.0, help="seconds between updates, default 1")
    p.add_argument("--once", action="store_true", help="print one snapshot without clearing the screen, then exit")
    a = p.parse_args(argv)
    if a.interval <= 0:
        p.error("interval must be greater than 0")
    addr = a.host if ":" in a.host else f"{a.host}:{PORT}"
    url = f"http://{addr}/api/stats"

    def fetch():
        with urllib.request.urlopen(url, timeout=5) as r:
            return render(json.load(r))

    try:
        out = fetch()
    except (OSError, ValueError) as e:  # not running / unreachable: say so once instead of retrying forever
        sys.exit(explain(addr, e))
    if a.once:
        print(out)
        return
    try:
        while True:
            print("\033[H\033[J" + out, flush=True)
            time.sleep(a.interval)
            try:
                out = fetch()
            except (OSError, ValueError) as e:  # lost while watching: keep the screen, keep retrying
                out = f"{explain(addr, e)}\n(retrying every {a.interval:g}s, Ctrl+C to quit)"
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
