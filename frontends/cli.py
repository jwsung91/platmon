#!/usr/bin/env python3
"""Terminal viewer for platmon. Reads the JSON API, so it runs anywhere; --local reads this host directly.

Usage: python3 -m frontends.cli [host[:port]] [interval_sec]   (default localhost:8080, 1s)
       python3 -m frontends.cli --local [interval_sec]         (no server needed)
Remote mode needs only this file: copied alone, `python3 cli.py <host>` works too.
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
    if args[:1] == ["--local"]:  # ponytail: kept until the platmon.py launcher replaces it
        # only local mode needs the collector, so remote use stays one file
        from collector import collect
        from collector.sampler import Sampler
        from frontends import terminal

        t = terminal.start(Sampler(collect, float(args[1]) if len(args) > 1 else 1.0).start())
        try:
            t and t.join()
        except KeyboardInterrupt:
            pass
        return
    host = args.pop(0) if args else "localhost:8080"
    where = f"http://{host if ':' in host else host + ':8080'}/api/stats"

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
