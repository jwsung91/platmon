#!/usr/bin/env python3
"""Remote terminal client for platmon: reads a host's /api/stats. Standalone; copy this file anywhere.

Usage: python3 frontends/cli.py [host[:port]] [interval_sec]   (default localhost:9797, 1s)
"""
import json
import sys
import time
import urllib.request


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
        lines.append(f"GPU   {bar(g['usage'])} {g['usage']:5.1f}%  {g['freq'] / 1e6:4.0f} MHz")
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
        lines.append(f"FAN   {f['name']}  " + "  ".join(v for v in vals if v))
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    host = args.pop(0) if args else "localhost:9797"
    where = f"http://{host if ':' in host else host + ':9797'}/api/stats"

    def fetch():
        with urllib.request.urlopen(where, timeout=5) as r:
            return json.load(r)
    interval = float(args[0]) if args else 1.0
    try:
        while True:
            try:
                out = render(fetch())
            except OSError as e:
                out = f"{where}: {e}"
            print("\033[H\033[J" + out, flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
