#!/usr/bin/env python3
"""CPU and memory of the real service (python3 platmon.py INI) as a separate process, polled like the web
page: /api/stats every second and, with --page, /api/observations and /api/history every 10 s (bench tool,
not product code). The service's own user+system time comes from /proc/<pid>/stat, so the poller's CPU is
never counted in it. One window per run: --warmup seconds, then --measure seconds.

  python3 benchmarks/service_cpu.py --ini default.ini --port 19797 --out default-1.json
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TICK = os.sysconf("SC_CLK_TCK")


def cpu_s(pid):
    """utime + stime of pid in seconds (fields 14 and 15 of /proc/<pid>/stat, after the command name)."""
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / TICK


def memory(pid):
    out = {}
    with open(f"/proc/{pid}/smaps_rollup") as f:
        for line in f:
            k, _, v = line.partition(":")
            if k in ("Rss", "Pss"):
                out[k.lower() + "_kib"] = int(v.split()[0])
    return out


def get(url):
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, len(r.read()), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, 0, time.monotonic() - t0
    except OSError:
        return -1, 0, time.monotonic() - t0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ini", required=True)
    p.add_argument("--port", type=int, required=True, help="the [http] port in the INI (loopback)")
    p.add_argument("--warmup", type=float, default=30)
    p.add_argument("--measure", type=float, default=120)
    p.add_argument("--page", action="store_true", help="also poll /api/observations and /api/history every 10 s")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    base = f"http://127.0.0.1:{a.port}"
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "platmon.py"), a.ini], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if get(base + "/api/status")[0] == 200:
                break
            time.sleep(0.1)
        results = {"stats": [], "observations": [], "history": []}
        start = end = None
        t_begin = time.monotonic()
        nxt, slow_next = t_begin, t_begin
        while True:
            now = time.monotonic()
            if start is None and now - t_begin >= a.warmup:
                start = (now, cpu_s(proc.pid), memory(proc.pid))
            if start is not None and now - start[0] >= a.measure:
                end = (now, cpu_s(proc.pid), memory(proc.pid))
                break
            r = get(base + "/api/stats")
            if start is not None:
                results["stats"].append(r)
            if a.page and now >= slow_next:
                for name, path in (("observations", "/api/observations"), ("history", "/api/history?points=120")):
                    r = get(base + path)
                    if start is not None:
                        results[name].append(r)
                slow_next += 10
            nxt += 1
            time.sleep(max(0.0, nxt - time.monotonic()))
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(10)
    elapsed = end[0] - start[0]
    out = {"ini": os.path.basename(a.ini), "page": a.page, "elapsed_s": elapsed, "cpu_s": end[1] - start[1],
           "cpu_pct_one_core": 100 * (end[1] - start[1]) / elapsed, "memory_start": start[2], "memory_end": end[2],
           "requests": {k: {"n": len(v), "errors": sum(1 for c, _, _ in v if c != 200),
                            "bytes_mean": sum(b for _, b, _ in v) / len(v) if v else None,
                            "latency_ms_max": max((t for _, _, t in v), default=0) * 1000} for k, v in results.items()},
           "exit": proc.returncode, "stderr_tail": proc.stderr.read().decode(errors="replace")[-500:],
           "python": platform.python_version()}
    with open(a.out, "w") as f:
        json.dump(out, f)
    print(json.dumps({k: out[k] for k in ("ini", "cpu_pct_one_core", "memory_end", "requests")}))


if __name__ == "__main__":
    main()
