#!/usr/bin/env python3
"""Terminal viewer for platmon. Reads only the JSON API, so it runs anywhere.

Usage: python3 cli.py [host[:port]] [interval_sec]   (default localhost:8080, 1s)
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


def render(s):
    up = int(s["uptime"])
    lines = [
        f"{s['model']}",
        f"{s['platform']}   " + (f"mode {s['power_mode']}   " if s["power_mode"] else "") + f"up {up // 86400}d {up % 86400 // 3600:02}:{up % 3600 // 60:02}",
        "",
    ]
    for i, c in enumerate(s["cpu"]):
        freq = f"  {c['freq'] / 1e6:4.0f} MHz" if c["freq"] else ""
        lines.append(f"CPU{i:<3}{bar(c['usage'])} {c['usage']:5.1f}%{freq}")
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
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost:8080"
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    url = f"http://{host if ':' in host else host + ':8080'}/api/stats"
    try:
        while True:
            try:
                with urllib.request.urlopen(url, timeout=5) as r:
                    out = render(json.load(r))
            except OSError as e:
                out = f"{url}: {e}"
            print("\033[H\033[J" + out, flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
