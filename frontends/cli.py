#!/usr/bin/env python3
"""platmon terminal client: live view of a platmon service, this device's by default.
Standalone (standard library only); scripts/install-cli.sh installs it as the `platmon` command.

Usage: platmon [host[:port]] [interval_sec] [--once]   (default localhost:9797, 1s)
The service itself runs in the background: scripts/systemd/install.sh or scripts/docker/start.sh.
"""
# platmon-cli: marker that lets scripts/install-cli.sh recognise (and only replace) its own command
import argparse
import json
import math
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


CPU_REASONS = {"warmup": "warming up", "counter_regressed": "counter went backwards", "no_ticks": "no ticks counted",
               "invalid_interval": "invalid interval", "gap": "restarting after a gap"}  # others: the code itself


def cpu_note(s):
    """Why CPU rows are missing (the service compares readings, so the first has none); empty if none are."""
    groups = {}
    for u in (s.get("cpu_sampling") or {}).get("unavailable") or []:
        groups.setdefault(CPU_REASONS.get(u["reason"], u["reason"]), []).append(f"CPU{u['id']}")
    if not groups:
        return ""
    if not s["cpu"] and len(groups) == 1:  # every core, one reason
        return f"CPU sampling: {next(iter(groups))}"
    return "CPU sampling: " + "; ".join(f"{' '.join(ids)} {why}" for why, ids in groups.items())


RATE_REASONS = {"warmup": "warming up", "gap": "restarting after a gap", "counter_regressed": "counter went backwards",
                "invalid_interval": "invalid interval", "identity_unavailable": "identity unknown",
                "namespace_changed": "namespace changed"}  # why rates are null; others: the code itself
MAX_ROWS = 12  # interfaces or disks listed; the rest are counted, all are in /api/stats


def per_s(v):
    """Bytes per second, binary units: 512 B/s, 1.5 KiB/s, 20.0 MiB/s."""
    for unit in ("B/s", "KiB/s", "MiB/s"):
        if abs(v) < 1024:
            return f"{v:.0f} {unit}" if unit == "B/s" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GiB/s"


def rows_of(items, kind, line):
    """One line per item (as the server sorted them): its name, then line(item) if it has rates, else why
    not. At most MAX_ROWS, then how many were left out."""
    width = min(16, max(len(i["name"]) for i in items))
    out = [f"  {i['name']:<{width}}  " + (line(i) if i.get("rates") else RATE_REASONS.get(i.get("reason"), str(i.get("reason"))))
           for i in items[:MAX_ROWS]]
    if len(items) > MAX_ROWS:
        out.append(f"  +{len(items) - MAX_ROWS} more {kind} (all in /api/stats)")
    return out


def network_line(i):
    r = i["rates"]
    bad = [f"{k} {i['rx'][k]}/{i['tx'][k]}" for k in ("errors", "dropped") if i["rx"][k] or i["tx"][k]]
    return (f"rx {per_s(r['rx_bytes_per_s'])}  tx {per_s(r['tx_bytes_per_s'])}  "
            f"{r['rx_packets_per_s']:.1f}/{r['tx_packets_per_s']:.1f} pkt/s"
            + ("  " + "  ".join(bad) + " (rx/tx, total)" if bad else ""))


def disk_line(d):
    r = d["rates"]
    return (f"read {per_s(r['read_bytes_per_s'])} ({r['reads_per_s']:.1f}/s)  "
            f"write {per_s(r['write_bytes_per_s'])} ({r['writes_per_s']:.1f}/s)  "
            f"I/O time {100 * r['io_time_ratio']:.1f}%" + (f"  in flight {d['in_flight']}" if d.get("in_flight") else ""))


def counters_lines(s):
    """Network interfaces (this process's namespace) and physical disks, with the rates the server computed;
    nothing for servers without them or with them off. I/O time is the share of the window with I/O in
    flight, not how saturated a disk is."""
    out = []
    net, dio = s.get("network"), s.get("disk_io")
    if isinstance(net, dict) and isinstance(net.get("interfaces"), list) and net["interfaces"]:
        out += ["NET   bytes/s, this process's network namespace"] + rows_of(net["interfaces"], "interfaces", network_line)
    if isinstance(dio, dict) and isinstance(dio.get("disks"), list) and dio["disks"]:
        out += ["IO    bytes/s per disk"] + rows_of(dio["disks"], "disks", disk_line)
    return out


def storage_lines(obs):
    """Filesystems and partitions from /api/observations, with the observation's own age; nothing when the
    group is off, has not been observed yet, or the server has no such endpoint."""
    groups = obs.get("groups") if isinstance(obs, dict) else None
    g = groups.get("storage") if isinstance(groups, dict) else None
    data, o = (g.get("data"), g.get("observation")) if isinstance(g, dict) else (None, None)
    if not isinstance(data, dict) or not isinstance(o, dict):
        return []
    head = f"STORAGE  observed {o['data_age_ms'] / 1000:.0f} s ago" + (" (not current)" if o.get("stale") else "")
    out = [head]
    for f in data.get("filesystems") or []:
        first, more = f["mount_points"][0], len(f["mount_points"]) - 1  # bind mounts can be dozens
        where = first["path"] + (" (ro)" if first["read_only"] else "") + (f" +{more} more" if more else "")
        dev = f["device"] or f"{f['major']}:{f['minor']}"
        if f["total_bytes"] is not None:  # a measured 0 is shown as 0
            pct = f" ({100 * f['used_bytes'] / f['total_bytes']:.0f}%)" if f["total_bytes"] else ""
            out.append(f"  {where}  {f['fstype']} {dev}  used {gib(f['used_bytes'])}/{gib(f['total_bytes'])}{pct}"
                       f"  available {gib(f['available_bytes'])}")
        else:
            out.append(f"  {where}  {f['fstype']} {dev}  capacity unknown")
    disks = {}
    for p in data.get("partitions") or []:
        disks.setdefault(p["disk"], []).append(p)
    for disk, parts in disks.items():
        mounted = sum(1 for p in parts if p["mount_points"])
        out.append(f"  {disk}: {len(parts)} partitions, {mounted} mounted")
    return out


def aged(body, seconds):
    """An /api/observations answer as of seconds after it arrived: each observation's ages grow by that
    much (a copy; the answer itself is kept as received)."""
    if not isinstance(body, dict) or not isinstance(body.get("groups"), dict):
        return body
    groups = {}
    for name, g in body["groups"].items():
        o = g.get("observation") if isinstance(g, dict) else None
        if isinstance(o, dict) and isinstance(o.get("data_age_ms"), (int, float)):
            g = {**g, "observation": {**o, "data_age_ms": o["data_age_ms"] + 1000 * seconds}}
        groups[name] = g
    return {**body, "groups": groups}


def wifi_lines(obs):
    """Wireless interfaces from /api/observations: the signal while connected, never the last one after."""
    groups = obs.get("groups") if isinstance(obs, dict) else None
    g = groups.get("wifi") if isinstance(groups, dict) else None
    data, o = (g.get("data"), g.get("observation")) if isinstance(g, dict) else (None, None)
    items = data.get("interfaces") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not isinstance(o, dict):
        return []
    age = f"observed {o['data_age_ms'] / 1000:.0f} s ago" + (" (not current)" if o.get("stale") else "")
    out = [f"WIFI  {age}"]
    for i in items:
        if not i["connected"]:
            out.append(f"  {i['name']}  not connected")
            continue
        signal = (f"{i['signal_dbm']} dBm" if i["signal_dbm"] is not None
                  else f"signal {i['signal_raw']} (unit not reported)" if i["signal_raw"] is not None else "signal n/a")
        extra = [f"link quality {i['link_quality']}" if i["link_quality"] is not None else "",
                 f"noise {i['noise_dbm']} dBm" if i["noise_dbm"] is not None else ""]
        out.append(f"  {i['name']}  {signal}" + "".join(f"  {e}" for e in extra if e))
    return out


def collection_note(s):
    """Optional groups that could not read everything ("Collection: temperature partial, gpu error");
    empty when all read fine or are just absent (no GPU, no fans), and for servers without collectors."""
    collectors = s.get("collectors")
    bad = [f"{name} {c['state']}" for name, c in (collectors.items() if isinstance(collectors, dict) else ())
           if name != "core" and isinstance(c, dict) and c.get("state") in ("partial", "error")]
    return "Collection: " + ", ".join(bad) if bad else ""


def render(s, obs=None):
    """The screen for a /api/stats answer s, and the storage lines when obs (an /api/observations answer)
    is given."""
    up = int(s["uptime"])
    system = system_line(s.get("system"))
    lines = [
        f"{s['model']}",
        f"{s['platform']}   " + (f"mode {s['power_mode']}   " if s["power_mode"] else "") + f"up {up // 86400}d {up % 86400 // 3600:02}:{up % 3600 // 60:02}",
        *([system] if system else []),
        *([note] if (note := collection_note(s)) else []),
        "",
    ]
    for c in s["cpu"]:
        freq = f"  {c['freq'] / 1e6:4.0f} MHz" if c["freq"] else ""
        lines.append(f"CPU{c['id']:<3}{bar(c['usage'])} {c['usage']:5.1f}%{freq}")
    note = cpu_note(s)
    if note:
        lines.append(note)
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
    extra = counters_lines(s) + storage_lines(obs) + wifi_lines(obs)
    if extra and lines[-1]:
        lines.append("")
    return "\n".join(lines + extra)


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
    if not (math.isfinite(a.interval) and a.interval > 0):  # nan and inf would crash in time.sleep()
        p.error("interval must be a number greater than 0")
    addr = a.host if ":" in a.host else f"{a.host}:{PORT}"
    url = f"http://{addr}/api/stats"

    obs = {"at": None, "body": None, "supported": True}

    def observations():
        """/api/observations at most every 10 s (it changes on its own, slower, cadence); none for servers
        without it, or when it cannot be read: the main view goes on."""
        now = time.monotonic()
        if obs["supported"] and (obs["at"] is None or now - obs["at"] >= 10):
            obs["at"] = now
            try:
                with urllib.request.urlopen(f"http://{addr}/api/observations", timeout=5) as r:
                    obs["body"] = json.load(r)
            except urllib.error.HTTPError as e:
                obs["supported"] = e.code != 404  # an older server: do not ask again
                obs["body"] = None
            except (OSError, ValueError):
                obs["body"] = None
        return aged(obs["body"], now - obs["at"]) if obs["body"] else None

    def fetch():
        with urllib.request.urlopen(url, timeout=5) as r:
            return render(json.load(r), observations())

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
