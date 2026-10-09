#!/usr/bin/env python3
"""CPU and memory of the real service (python3 platmon.py INI) as a separate process, polled like the web
page: /api/stats every second and, with --page, /api/observations and /api/history every 10 s (bench tool,
not product code). The service's own user+system time comes from /proc/<pid>/stat, so the poller's CPU is
never counted in it. One window per run: --warmup seconds, then --measure seconds.

  python3 benchmarks/service_cpu.py --ini default.ini --port 19797 --out default-1.json
"""
import argparse
import configparser
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

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


def get(url, body=False):
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = r.read()
            result = r.status, len(data), time.monotonic() - t0
            return (*result, json.loads(data)) if body else result
    except urllib.error.HTTPError as e:
        result = e.code, 0, time.monotonic() - t0
    except OSError:
        result = -1, 0, time.monotonic() - t0
    return (*result, None) if body else result


def history_summary(doc):
    series = doc.get("series", {})
    return {"series": len(series), "points": sum(len(p) for p in series.values()),
            "max_points": max((len(p) for p in series.values()), default=0),
            "oldest_ms": max((p[0][1] for p in series.values() if p), default=0),
            "domains": dict(Counter(k.split('/')[1] if k.startswith('observation/') else 'core' for k in series)),
            "dropped_series": doc.get("dropped_series"), "instance_id": doc.get("instance_id")}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ini", required=True)
    p.add_argument("--port", type=int, required=True, help="the [http] port in the INI (loopback)")
    p.add_argument("--warmup", type=float, default=30)
    p.add_argument("--measure", type=float, default=120)
    p.add_argument("--page", action="store_true", help="also poll /api/observations and /api/history every 10 s")
    p.add_argument("--out", required=True)
    p.add_argument("--source-sha", default=None, help="exact archived commit being measured")
    a = p.parse_args(argv)
    config = configparser.ConfigParser()
    config.read(a.ini)
    history_enabled = config.getboolean('history', 'enabled', fallback=True)
    interval_ms = config.getfloat('core', 'interval', fallback=1.0) * 1000
    base = f"http://127.0.0.1:{a.port}"
    # Never accidentally measure or terminate an existing service on this port.
    with socket.socket() as check:
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # match HTTPServer; allow prior TIME_WAIT
        check.bind(("127.0.0.1", a.port))
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "platmon.py"), a.ini], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    samples, health, history_samples, observation_samples = [], [], [], []
    errors = Counter()
    published = {}
    final_documents = {}
    forced_kill = False
    try:
        for _ in range(100):
            status = get(base + "/api/status", True)
            if status[0] == 200 and status[3].get('ready'):
                break
            if proc.poll() is not None:
                raise RuntimeError("candidate exited during startup")
            time.sleep(0.1)
        else:
            raise RuntimeError("candidate did not become ready")
        health.append(status[3])
        results = {"stats": [], "observations": [], "history": []}
        start = end = None
        t_begin = time.monotonic()
        nxt, slow_next, memory_next = t_begin, t_begin, t_begin
        while True:
            now = time.monotonic()
            if start is None and now - t_begin >= a.warmup:
                start = (now, cpu_s(proc.pid), memory(proc.pid))
            if start is not None and now - start[0] >= a.measure:
                end = (now, cpu_s(proc.pid), memory(proc.pid))
                break
            r = get(base + "/api/stats", True)
            if start is not None:
                results["stats"].append(r[:3])
                if r[3]:
                    sample = r[3].get('sample', {})
                    published[sample['sequence']] = sample['duration_ms']
                    if sample['instance_id'] != health[0]['instance_id']:
                        errors['instance_changed'] += 1
                    if sample.get('data_age_basis') != 'oldest_current_read_start':
                        errors['freshness_fallback'] += 1
                    for name, value in r[3].get('collectors', {}).items():
                        if value.get('state') in ('error', 'partial'):
                            errors['collector_' + name + '_' + value['state']] += 1
                final_documents['stats'] = r[3]
            if a.page and now >= slow_next:
                for name, path in (("observations", "/api/observations"), ("history", "/api/history?points=120")):
                    r = get(base + path, True)
                    if start is not None:
                        results[name].append(r[:3])
                    final_documents[name] = r[3]
                    if r[3] and name == 'history':
                        history_samples.append({'elapsed_s': now - t_begin, **history_summary(r[3])})
                    if r[3] and name == 'observations':
                        observation_samples.append({'elapsed_s': now - t_begin, 'groups': {
                            k: {'state': v['state'], 'observation': v['observation'], 'collector': v['collector']}
                            for k, v in r[3]['groups'].items()}})
                slow_next += 10
            if now >= memory_next:
                samples.append({'elapsed_s': now - t_begin, **memory(proc.pid),
                                'threads': len(os.listdir(f'/proc/{proc.pid}/task'))})
                memory_next += 10
            nxt += 1
            time.sleep(max(0.0, nxt - time.monotonic()))
        # These diagnostics are outside the measured CPU window.
        health.append(get(base + '/api/status', True)[3])
        if a.page:
            final_documents['history_full'] = get(base + '/api/history?points=600', True)[3]
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            forced_kill = True
            proc.kill()
            proc.wait(10)
    elapsed = end[0] - start[0]
    stderr = proc.stderr.read().decode(errors='replace')
    missing = max(published) - min(published) + 1 - len(published) if published else None
    out = {"ini": os.path.basename(a.ini), "page": a.page, "elapsed_s": elapsed, "cpu_s": end[1] - start[1],
           "cpu_pct_one_core": 100 * (end[1] - start[1]) / elapsed, "memory_start": start[2], "memory_end": end[2],
           "requests": {k: {"n": len(v), "statuses": dict(Counter(c for c, _, _ in v)),
                            "errors": sum(1 for c, _, _ in v if c != (404 if k == 'history' and not history_enabled else 200)),
                            "bytes_mean": sum(b for _, b, _ in v) / len(v) if v else None,
                            "latency_ms_max": max((t for _, _, t in v), default=0) * 1000} for k, v in results.items()},
           "exit": proc.returncode, "forced_kill": forced_kill,
           "pid": proc.pid, "pid_gone": not os.path.exists(f'/proc/{proc.pid}'),
           "port_closed": get(base + '/api/status')[0] == -1,
           "stderr_tail": stderr[-2000:], 'stderr_bytes': len(stderr.encode()),
           'stderr_sha256': hashlib.sha256(stderr.encode()).hexdigest(),
           'collection_failures_logged': stderr.count('platmon: collect failed:'),
           'stale_collections_dropped_logged': stderr.count('result dropped'),
           'observed_samples': {'count': len(published), 'missing_sequences': missing,
                                'duration_ms_max': max(published.values(), default=None),
                                'overruns': sum(v > interval_ms for v in published.values())},
           "python": platform.python_version(), 'source_sha': a.source_sha,
           'ini_sha256': hashlib.sha256(open(a.ini, 'rb').read()).hexdigest(),
           'memory_samples': samples, 'health': health,
           'diagnostic_counts': dict(errors), 'history_samples': history_samples,
           'observation_samples': observation_samples, 'final_documents': final_documents}
    with open(a.out, "w") as f:
        json.dump(out, f)
    print(json.dumps({k: out[k] for k in ("ini", "cpu_pct_one_core", "memory_end", "requests")}))


if __name__ == "__main__":
    main()
