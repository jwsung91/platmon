#!/usr/bin/env python3
"""Measure what platmon costs per collection interval, and what the passive Network/Disk/PSI prototype
(benchmarks/passive.py) adds. Bench tool only: nothing here changes the product or its defaults.

  serve   one bench server: the product Sampler, collect_recorded and HTTP handler, plus a timed passive
          callback (B0: no-op, B1: Passive). Records into fixed-size buffers, writes one JSON at the end.
  client  a synthetic API client in its own process: GET /api/stats every --period seconds.
  probe   a standalone periodic read (noop, wireless, statvfs) for the conditional features.
  run     runs a plan of the above one at a time with a time/window budget and guards; appends results.jsonl.
  report  aggregates results.jsonl into the tables of docs/performance/low-overhead-cadence.md.

Usage, see docs/performance/low-overhead-cadence.md:
  python3 benchmarks/cadence.py run --out DIR --alias orin --phase matrix --intervals 0.5,1,2,5
  python3 benchmarks/cadence.py report DIR/results.jsonl
"""
import argparse
import array
import errno
import glob
import hashlib
import json
import math
import os
import platform
import resource
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
mono = time.monotonic_ns
tcpu = time.thread_time_ns
LOCAL_FS = ("ext4", "ext3", "ext2", "xfs", "btrfs", "f2fs", "vfat", "exfat")  # statvfs allowlist by type


# ---- calculations (tested in tests/test_bench_cadence.py) ----

def cpu_pct_one_core(start, end, elapsed_s):
    """Process CPU (user+system) over elapsed_s as % of ONE core; never divided by the CPU count."""
    used = (end["ru_utime"] + end["ru_stime"]) - (start["ru_utime"] + start["ru_stime"])
    return 100 * used / elapsed_s


def percentile(values, p):
    """Nearest-rank percentile; None for no values (never 0)."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)]


def dist(values):
    v = [x for x in values if x is not None]
    return {"n": len(v), "mean": sum(v) / len(v) if v else None, "p50": percentile(v, 50),
            "p95": percentile(v, 95), "max": max(v) if v else None}


def slope_per_min(points):
    """Least-squares slope of (t_ns, value) points per minute; None for fewer than 3 points."""
    if len(points) < 3:
        return None
    n = len(points)
    xs = [t / 60e9 for t, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else None


def rusage(who=resource.RUSAGE_SELF):
    r = resource.getrusage(who)
    return {k: getattr(r, k) for k in ("ru_utime", "ru_stime", "ru_maxrss", "ru_minflt", "ru_majflt",
                                       "ru_nvcsw", "ru_nivcsw")}


def sha256_files(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        with open(p, "rb") as f:
            h.update(os.path.relpath(p, ROOT).encode() + b"\0" + f.read())
    return h.hexdigest()[:16]


def source_hash():
    """The product code the bench runs (collector, frontends, platmon.py)."""
    return sha256_files(glob.glob(f"{ROOT}/collector/*.py") + glob.glob(f"{ROOT}/frontends/*.py")
                        + glob.glob(f"{ROOT}/frontends/web/index.html") + [f"{ROOT}/platmon.py"])


def bench_hash():
    return sha256_files(glob.glob(f"{HERE}/*.py"))


class Table:
    """Fixed-size int64 columns allocated up front, so recording does not grow memory with samples."""

    def __init__(self, fields, capacity):
        self.fields, self.capacity, self.n, self.dropped = fields, capacity, 0, 0
        self.cols = [array.array("q", bytes(8 * capacity)) for _ in fields]
        self.lock = threading.Lock()

    def add(self, *values):
        with self.lock:
            if self.n >= self.capacity:
                self.dropped += 1
                return
            for col, v in zip(self.cols, values):
                col[self.n] = v
            self.n += 1

    def nbytes(self):
        return sum(c.itemsize * len(c) for c in self.cols)

    def dump(self):
        return {"fields": self.fields, "dropped": self.dropped,
                "rows": [[c[i] for c in self.cols] for i in range(self.n)]}


def rows(table, t0=None, t1=None):
    """Dumped table rows as dicts, keeping those whose first field (a mono ns time) is in [t0, t1)."""
    out = [dict(zip(table["fields"], r)) for r in table["rows"]]
    return [r for r in out if (t0 is None or r[table["fields"][0]] >= t0) and (t1 is None or r[table["fields"][0]] < t1)]


def statm_rss():
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def smaps_rollup():
    out = {}
    try:
        with open("/proc/self/smaps_rollup") as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in ("Rss", "Pss", "Private_Dirty", "Anonymous"):
                    out[k.lower() + "_bytes"] = int(v.split()[0]) * 1024
    except OSError as e:
        out["error"] = errno.errorcode.get(e.errno, str(e))
    return out


def boottime_ns():
    try:
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return None


def mark():
    """Process counters at a window edge."""
    return {"mono": mono(), "boot": boottime_ns(), "process_time_ns": time.process_time_ns(),
            "self": rusage(), "children": rusage(resource.RUSAGE_CHILDREN), "rss_bytes": statm_rss(),
            "smaps": smaps_rollup(), "threads": threading.active_count()}


def scope_of(stats, passive):
    """Counts that must match between runs that are compared (see mismatches)."""
    net = passive.get("network", {})
    disk = passive.get("disk", {})
    return {
        "cpu_rows": len(stats.get("cpu") or []), "temperature": len(stats.get("temperature") or {}),
        "power": len(stats.get("power") or {}), "fans": len(stats.get("fans") or []),
        "sensor_meta": len(stats.get("sensor_meta") or {}),
        "collectors": {k: v.get("state") for k, v in (stats.get("collectors") or {}).items()},
        "interfaces": len(net.get("interfaces", {})),
        "physical_interfaces": sum(1 for i in net.get("interfaces", {}).values() if i["physical"]),
        "block_devices": len(disk.get("devices", {})),
        "psi": {k: v["state"] for k, v in passive.get("pressure", {}).items()},
    }


# ---- serve ----

def serve(a):
    sys.path.insert(0, ROOT)
    import functools
    from http.server import ThreadingHTTPServer

    from benchmarks.passive import Passive
    from collector import BOARD, PLATFORM, collect_recorded
    from collector.common import CpuCounters
    from collector.sampler import Sampler, pick_clock
    from frontends import server

    cap = int((a.warmup + a.measure) / a.interval) + 64
    t_collect = Table(["t", "prod_ns", "prod_cpu_ns", "passive_ns", "passive_cpu_ns"], cap)
    t_attempt = Table(["t", "started", "elapsed_ns", "cpu_ns", "duration_ns", "ok", "sequence"], cap)
    req_cap = int((a.warmup + a.measure + 10) * max(a.expect_rps, 1)) + 64
    t_http = Table(["t", "elapsed_ns", "cpu_ns", "read_ns", "read_cpu_ns", "bytes", "code", "sequence"], req_cap)
    t_mem = Table(["t", "rss_bytes"], int((a.warmup + a.measure) / 10) + 8)

    clock = pick_clock()
    cpu = CpuCounters(clock[0], max_gap=max(3 * a.interval, 5.0))
    product = functools.partial(collect_recorded, cpu, {}, clock[0])
    probe = Passive() if a.variant == "B1" else (lambda: None)

    def collect():  # same wrapper in B0 and B1; only the callback differs
        t0, c0 = mono(), tcpu()
        c = product()
        t1, c1 = mono(), tcpu()
        extra = probe()
        t2, c2 = mono(), tcpu()
        if extra is not None:
            c.stats["_bench_passive"] = extra  # experimental, not a product field
        t_collect.add(t0, t1 - t0, c1 - c0, t2 - t1, c2 - c1)
        return c

    local = threading.local()

    class BenchSampler(Sampler):
        def _attempt(self):
            t0, c0 = mono(), tcpu()
            started = super()._attempt()
            r = self._attempt_result
            t_attempt.add(t0, started, mono() - t0, tcpu() - c0, r["duration_ns"], r["state"] == "ok", self._sequence)
            return started

        def read(self, timeout=0.0):
            t0, c0 = mono(), tcpu()
            out = super().read(timeout)
            local.read = (mono() - t0, tcpu() - c0, (out[0] or {}).get("sample", {}).get("sequence", 0))
            return out

    sampler = BenchSampler(collect, a.interval, clock=clock)
    base = server.make_handler(sampler, True)

    class Handler(base):
        def do_GET(self):
            self._bytes, self._code, local.read = 0, 0, (0, 0, 0)
            t0, c0 = mono(), tcpu()
            super().do_GET()
            t_http.add(t0, mono() - t0, tcpu() - c0, *local.read[:2], self._bytes, self._code, local.read[2])

        def reply(self, code, body, ctype):
            self._bytes, self._code = len(body), code
            super().reply(code, body, ctype)

    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    sampler.start()
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    print(f"ready {PLATFORM} {BOARD.__name__ if BOARD else 'none'}", flush=True)

    def sleep_until(deadline):  # main thread: an RSS sample every 10 s, nothing else
        while (left := deadline - mono()) > 0:
            time.sleep(min(10.0, left / 1e9))
            t_mem.add(mono(), statm_rss())

    begin = mono()
    sleep_until(begin + int(a.warmup * 1e9))
    start = mark()
    sleep_until(start["mono"] + int(a.measure * 1e9))
    end = mark()
    sampler.stop()
    httpd.shutdown()
    stats = sampler.read()[0] or {}
    scope = scope_of(stats, Passive()() if a.variant == "B0" else stats.get("_bench_passive", {}))
    elapsed = (end["mono"] - start["mono"]) / 1e9
    boot = None if start["boot"] is None else (end["boot"] - start["boot"]) / 1e9
    out = {
        "kind": "serve", "run_id": a.run_id, "variant": a.variant, "interval_s": a.interval, "warmup_s": a.warmup,
        "measure_s": a.measure, "platform": PLATFORM, "begin_mono": begin, "start": start, "end": end,
        "measured_elapsed_s": elapsed, "boottime_elapsed_s": boot,
        "clock_jump": boot is not None and abs(boot - elapsed) > 1.0,  # suspend or a large clock step
        "cpu_pct_one_core": cpu_pct_one_core(start["self"], end["self"], elapsed),
        "cpu_pct_all_cores": cpu_pct_one_core(start["self"], end["self"], elapsed) / os.cpu_count(),
        "children_cpu_s": (end["children"]["ru_utime"] + end["children"]["ru_stime"])
                          - (start["children"]["ru_utime"] + start["children"]["ru_stime"]),
        "buffer_bytes": sum(t.nbytes() for t in (t_collect, t_attempt, t_http, t_mem)),
        "scope": scope, "passive_io": {k: getattr(probe, k, None) for k in ("reads", "read_bytes", "lookups")},
        "tables": {"collect": t_collect.dump(), "attempt": t_attempt.dump(), "http": t_http.dump(),
                   "mem": t_mem.dump()},
        "python": platform.python_version(), "source_hash": source_hash(), "bench_hash": bench_hash(),
    }
    with open(a.out, "w") as f:
        json.dump(out, f)


# ---- client ----

def client(a):
    n = int(a.duration / a.period) + 8
    t = Table(["t", "latency_ns", "bytes", "status"], n)
    deadline = mono() + int(a.duration * 1e9)
    nxt = mono()
    while nxt < deadline:
        time.sleep(max(0, (nxt - mono()) / 1e9))
        t0, size, status = mono(), 0, 0
        try:
            with urllib.request.urlopen(a.url, timeout=5) as r:
                size, status = len(r.read()), r.status
        except OSError as e:
            status = getattr(e, "code", -1) or -1  # -1: no HTTP answer (refused, timeout)
        t.add(t0, mono() - t0, size, status)
        nxt = max(nxt + int(a.period * 1e9), mono())  # a late request does not trigger a burst of catch-ups
    with open(a.out, "w") as f:
        json.dump({"kind": "client", "period_s": a.period, "rusage": rusage(), "table": t.dump()}, f)


# ---- probe (conditional features) ----

def parse_wireless(text):
    """{iface: signal level dBm} from /proc/net/wireless; a row is only there while associated."""
    out = {}
    for line in text.splitlines()[2:]:
        name, sep, rest = line.partition(":")
        f = rest.split()
        if sep and len(f) >= 3:
            out[name.strip()] = float(f[2].rstrip("."))
    return out


def local_mounts(text):
    """Mount points of local block filesystems from /proc/self/mountinfo; network, FUSE, autofs, pseudo and
    unknown types are left out, so statvfs never wakes an automount or a remote server."""
    out = []
    for line in text.splitlines():
        left, _, right = line.partition(" - ")
        fstype, source = (right.split() + ["", ""])[:2]
        if fstype in LOCAL_FS and source.startswith("/dev/"):
            out.append(left.split()[4].replace("\\040", " "))
    return sorted(set(out))


def probe(a):
    """Calls one feature every --period seconds for --duration. statvfs runs in one worker thread; while a
    call is still running the next tick is skipped (counted), never stacked."""
    def noop():
        return 1, None

    def wireless():
        with open("/proc/net/wireless") as f:
            levels = parse_wireless(f.read())
        return len(levels), (max(levels.values()) if levels else None)

    mounts = []

    def mountinfo():
        with open("/proc/self/mountinfo") as f:
            mounts[:] = local_mounts(f.read())
        return len(mounts), None

    def statvfs():
        for m in mounts:
            os.statvfs(m)
        return len(mounts), None

    steps = {"noop": [noop], "wireless": [wireless], "statvfs": [mountinfo, statvfs]}[a.feature]
    n = int(a.duration / a.period) + 8
    t = Table(["t", "step", "elapsed_ns", "cpu_ns", "count", "value_x1000", "ok"], n * len(steps) + 2 * 100 + 8)
    busy = threading.Event()
    skipped = [0]

    def tick(label_offset=0):  # busy is set by the caller, before the thread starts
        try:
            for i, fn in enumerate(steps):
                t0, c0 = mono(), tcpu()
                try:
                    count, value = fn()
                    ok = 1
                except OSError:
                    count, value, ok = 0, None, 0
                t.add(t0, i + label_offset, mono() - t0, tcpu() - c0, count,
                      -10**12 if value is None else int(value * 1000), ok)
        finally:
            busy.clear()

    start = mark()
    deadline = start["mono"] + int(a.duration * 1e9)
    nxt = mono()
    while nxt < deadline:
        time.sleep(max(0, (nxt - mono()) / 1e9))
        if busy.is_set():
            skipped[0] += 1
        else:
            busy.set()
            threading.Thread(target=tick, daemon=True).start()
        nxt += int(a.period * 1e9)
    time.sleep(max(0, (deadline - mono()) / 1e9))  # the window is the full duration, also for long periods
    end = mark()
    elapsed = (end["mono"] - start["mono"]) / 1e9
    for _ in range(50):  # a call still running is waited for up to 5 s, never killed or repeated
        if not busy.is_set():
            break
        time.sleep(0.1)
    pending = busy.is_set()
    if a.burst and not pending:  # back-to-back calls, reported apart from the real cadence (step + 10)
        for _ in range(a.burst):
            busy.set()
            tick(10)
    with open(a.out, "w") as f:
        json.dump({"kind": "probe", "run_id": a.run_id, "feature": a.feature, "period_s": a.period,
                   "measured_elapsed_s": elapsed, "cpu_pct_one_core": cpu_pct_one_core(start["self"], end["self"], elapsed),
                   "start": start, "end": end, "skipped_ticks": skipped[0], "pending_at_end": pending,
                   "mounts": len(mounts), "table": t.dump(), "python": platform.python_version(),
                   "bench_hash": bench_hash()}, f)


# ---- run (orchestrator) ----

def plan(phase, intervals, final=None):
    """The conditions of one phase, in run order. B0 B1 B1 B0 per interval, so a drift over time does not
    favour one variant."""
    out = []
    if phase == "matrix":
        for iv in intervals:
            out += [dict(kind="serve", variant=v, interval=iv, clients=1, poll=1.0, measure=120) for v in ("B0", "B1", "B1", "B0")]
    elif phase == "clients":
        for clients, poll in ((0, 1.0), (3, 1.0), (1, 2.0)):
            out += [dict(kind="serve", variant=v, interval=1.0, clients=clients, poll=poll, measure=120) for v in ("B0", "B1")]
    elif phase == "final":
        measure = min(600, max(300, 120 * final))
        out += [dict(kind="serve", variant=v, interval=final, clients=1, poll=1.0, measure=measure) for v in ("B0", "B1")]
    elif phase == "probes":
        out += [dict(kind="probe", feature="noop", period=1.0, measure=120)]
        out += [dict(kind="probe", feature="wireless", period=p, measure=120) for p in (1.0, 2.0, 5.0)]
        out += [dict(kind="probe", feature="statvfs", period=p, measure=120) for p in (30.0, 60.0)]
    else:
        raise ValueError(f"unknown phase {phase}")
    for c in out:
        c["phase"] = phase
    return out


def budget_left(done, cond, warmup, budget_s, max_windows):
    """None if cond fits the remaining budget (wall time and windows), else why not."""
    used = sum(r.get("wall_s", 0) for r in done)
    windows = sum(1 for r in done if r.get("counted", True))
    need = cond["measure"] + (warmup if cond["kind"] == "serve" else 0) + 15
    if windows + 1 > max_windows:
        return f"window budget spent ({windows}/{max_windows})"
    if used + need > budget_s:
        return f"time budget spent ({used:.0f}+{need:.0f} s > {budget_s:.0f} s)"
    return None


def device_state():
    """Temperatures, clocks and throttle flags, read between runs only (never inside a window)."""
    def cat(p):
        try:
            with open(p) as f:
                return f.read().strip()
        except OSError:
            return None
    temps = {os.path.basename(z): cat(f"{z}/temp") for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*"))}
    freqs = {os.path.basename(os.path.dirname(c)): cat(c)
             for c in sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq"))}
    out = {"mono": mono(), "temps_mC": temps, "cpufreq_khz": freqs, "loadavg": cat("/proc/loadavg")}
    if shutil.which("vcgencmd"):
        r = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True)
        out["throttled"] = r.stdout.strip()
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":")
            mem[k] = int(v.split()[0]) * 1024
    out["mem_available"] = mem["MemAvailable"]
    return out


def throttled_now(state):
    """Current (not sticky) throttle bits from vcgencmd get_throttled, or None without vcgencmd."""
    t = state.get("throttled")
    return None if not t or "=" not in t else int(t.split("=")[1], 16) & 0xF


def guard(state, out_dir, watch_url):
    """None if it is safe to start the next run, else why not."""
    if throttled_now(state):
        return f"current throttle/undervoltage bits set: {state['throttled']}"
    if state["mem_available"] < 300 * 2**20:
        return "less than 300 MiB available memory"
    if shutil.disk_usage(out_dir).free < 500 * 2**20:
        return "less than 500 MiB free disk"
    if watch_url:
        try:
            with urllib.request.urlopen(watch_url, timeout=5) as r:
                if r.status != 200:
                    return f"watched service answered {r.status}"
        except OSError as e:
            return f"watched service did not answer: {e}"
    return None


def manifest(alias):
    def cat(p):
        try:
            with open(p) as f:
                return f.read().strip().rstrip("\0")
        except OSError:
            return None

    def cmd(*args):
        if not shutil.which(args[0]):
            return None
        r = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr).strip()
    sys.path.insert(0, ROOT)
    from collector import PLATFORM, collect
    stats = collect()  # one-off reading for the sensor counts
    nets = sorted(os.listdir("/sys/class/net"))
    release = os.uname().release
    mem = cat("/proc/meminfo").split("\n")[0]
    return {
        "kind": "manifest", "alias": alias, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "platform": PLATFORM,
        "model": cat("/proc/device-tree/model") or cat("/sys/class/dmi/id/product_name"),
        "os": stats["system"]["os"], "kernel": release, "arch": platform.machine(),
        "python": platform.python_version(), "python_bits": 64 if sys.maxsize > 2**32 else 32,
        "userland_bits": cmd("getconf", "LONG_BIT"), "online_cpus": cat("/sys/devices/system/cpu/online"),
        "cpu_count": os.cpu_count(), "mem_total": mem,
        "governors": sorted(set(filter(None, (cat(p) for p in glob.glob("/sys/devices/system/cpu/cpufreq/policy*/scaling_governor"))))),
        "nvpmodel": cmd("nvpmodel", "-q"), "l4t": (cat("/etc/nv_tegra_release") or "").split("\n")[0] or None,
        "throttled": cmd("vcgencmd", "get_throttled"),
        "block_devices": {d: {"removable": cat(f"/sys/block/{d}/removable"), "rotational": cat(f"/sys/block/{d}/queue/rotational")}
                          for d in sorted(os.listdir("/sys/block"))},
        "root_source": next((l.split()[0] for l in cat("/proc/mounts").split("\n") if l.split()[1] == "/"), None),
        "interfaces": {n: os.path.exists(f"/sys/class/net/{n}/device") for n in nets},
        "psi": {n: os.path.exists(f"/proc/pressure/{n}") for n in ("cpu", "memory", "io")},
        "wireless": parse_wireless(cat("/proc/net/wireless") or ""),
        "sensors": {k: len(stats.get(k) or []) for k in ("temperature", "power", "fans", "cpu")},
        "mode": "wsl" if "microsoft" in release.lower() else ("container" if os.path.exists("/.dockerenv") else "native"),
        "top_processes": cmd("ps", "-eo", "pcpu,comm", "--sort=-pcpu", "--no-headers")[:400],
        "clocks": {n: dict(vars(time.get_clock_info(n))) for n in ("monotonic", "process_time", "thread_time", "perf_counter")},
        "source_hash": source_hash(), "bench_hash": bench_hash(),
    }


def run(a):
    os.makedirs(a.out, exist_ok=True)
    results = os.path.join(a.out, "results.jsonl")
    done = []
    if os.path.exists(results):  # the budget counts every earlier phase in this directory
        with open(results) as f:
            done = [json.loads(l) for l in f if l.strip()]
    if not any(r["kind"] == "manifest" for r in done):
        done.append(manifest(a.alias))
        with open(results, "a") as f:
            f.write(json.dumps(done[-1]) + "\n")
    conds = plan(a.phase, [float(x) for x in a.intervals.split(",")] if a.intervals else [], a.final)
    for c in conds:
        c["measure"] = a.measure or c["measure"]  # a shorter window is for smoke tests only
    me = sys.executable
    stop = None
    for i, c in enumerate(conds):
        run_id = f"{a.alias}-{a.phase}-{i:02d}-{uuid.uuid4().hex[:6]}"
        rec = {"kind": "run", "run_id": run_id, "alias": a.alias, "cond": c, "source_sha": a.source_sha,
               "order": i, "counted": False}
        why = stop or budget_left([r for r in done if r["kind"] == "run"], c, a.warmup, a.budget_min * 60, a.max_windows)
        before = device_state()
        why = why or guard(before, a.out, a.watch_url)
        if why:
            rec.update(valid=False, skipped=why)
            stop = stop or why
            print(f"{run_id}: skipped: {why}", flush=True)
        else:
            t0 = time.time()
            rec.update(started=time.strftime("%Y-%m-%dT%H:%M:%S%z"), counted=True, before=before)
            rec.update(execute(me, run_id, c, a))
            after = device_state()
            rec.update(after=after, wall_s=time.time() - t0)
            new_throttle = throttled_now(after)
            if new_throttle:
                rec.update(valid=False, invalid=f"throttle bits during run: {after['throttled']}")
                stop = rec["invalid"]
            print(f"{run_id}: {c} valid={rec['valid']} {rec.get('invalid', '')}", flush=True)
            if rec.get("timeout"):
                stop = "a measurement process did not end in time"
        done.append(rec)
        with open(results, "a") as f:
            f.write(json.dumps(rec) + "\n")


def execute(me, run_id, c, a):
    """One condition: the server (or probe) and its clients as separate processes; returns their results."""
    tmp = os.path.join(a.out, "tmp")
    os.makedirs(tmp, exist_ok=True)
    out = {"valid": True}
    if c["kind"] == "probe":
        path = f"{tmp}/{run_id}.json"
        p = subprocess.Popen([me, __file__, "probe", "--feature", c["feature"], "--period", str(c["period"]),
                              "--duration", str(c["measure"]), "--out", path, "--run-id", run_id,
                              "--burst", "100" if c["feature"] == "statvfs" else "0"])
        try:
            p.wait(timeout=c["measure"] + 60)
        except subprocess.TimeoutExpired:
            p.kill()
            return {"valid": False, "invalid": "probe timeout", "timeout": True}
        if p.returncode:
            return {"valid": False, "invalid": f"probe exit {p.returncode}"}
        with open(path) as f:
            out["probe"] = json.load(f)
        os.remove(path)
        return out
    path = f"{tmp}/{run_id}.serve.json"
    srv = subprocess.Popen([me, __file__, "serve", "--variant", c["variant"], "--interval", str(c["interval"]),
                            "--warmup", str(a.warmup), "--measure", str(c["measure"]), "--port", str(a.port),
                            "--out", path, "--run-id", run_id, "--expect-rps", str(c["clients"] / c["poll"])],
                           stdout=subprocess.PIPE, text=True)
    ready = srv.stdout.readline()
    if not ready.startswith("ready"):
        srv.kill()
        return {"valid": False, "invalid": f"server did not start: {ready!r}"}
    clients = [subprocess.Popen([me, __file__, "client", "--url", f"http://127.0.0.1:{a.port}/api/stats",
                                 "--period", str(c["poll"]), "--duration", str(a.warmup + c["measure"] + 2),
                                 "--out", f"{tmp}/{run_id}.client{k}.json"]) for k in range(c["clients"])]
    try:
        srv.wait(timeout=a.warmup + c["measure"] + 60)
    except subprocess.TimeoutExpired:
        srv.kill()
        for p in clients:
            p.kill()
        return {"valid": False, "invalid": "server timeout", "timeout": True}
    for p in clients:
        try:
            p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            p.kill()
            out.update(valid=False, invalid="client timeout")
    if srv.returncode:
        return {"valid": False, "invalid": f"server exit {srv.returncode}"}
    with open(path) as f:
        out["serve"] = json.load(f)
    os.remove(path)
    out["clients"] = []
    for k in range(c["clients"]):
        p = f"{tmp}/{run_id}.client{k}.json"
        with open(p) as f:
            out["clients"].append(json.load(f))
        os.remove(p)
    if out["serve"]["clock_jump"]:
        out.update(valid=False, invalid="clock jump (suspend?) during the window")
    return out


# ---- report ----

def summarize_serve(rec):
    """One run's numbers, from the measured window only (warmup excluded, actual elapsed time)."""
    s = rec["serve"]
    t0, t1 = s["start"]["mono"], s["end"]["mono"]
    att = rows(s["tables"]["attempt"], t0, t1)
    col = rows(s["tables"]["collect"], t0, t1)
    http = rows(s["tables"]["http"], t0, t1)
    mem = rows(s["tables"]["mem"], t0, t1 + 1)
    started = [r["started"] for r in att]
    gaps = [(b - a) / 1e6 for a, b in zip(started, started[1:])]
    interval_ms = s["interval_s"] * 1000
    lat = [r for c in rec.get("clients", []) for r in rows(c["table"], t0, t1)]
    st, en = s["start"]["self"], s["end"]["self"]
    return {
        "run_id": rec["run_id"], "alias": rec["alias"], "phase": rec["cond"]["phase"], "variant": s["variant"],
        "interval_s": s["interval_s"], "clients": rec["cond"]["clients"], "poll_s": rec["cond"]["poll"],
        "valid": rec["valid"], "invalid": rec.get("invalid"), "order": rec["order"],
        "measured_elapsed_s": s["measured_elapsed_s"], "sample_count": sum(r["ok"] for r in att),
        "failed_attempts": sum(1 for r in att if not r["ok"]),
        "process_user_s": en["ru_utime"] - st["ru_utime"], "process_system_s": en["ru_stime"] - st["ru_stime"],
        "cpu_pct_one_core": s["cpu_pct_one_core"],
        "process_time_pct": 100 * (s["end"]["process_time_ns"] - s["start"]["process_time_ns"]) / 1e9 / s["measured_elapsed_s"],
        "children_cpu_s": s["children_cpu_s"],
        "passive_ms": dist([r["passive_ns"] / 1e6 for r in col]),
        "passive_cpu_ms": dist([r["passive_cpu_ns"] / 1e6 for r in col]),
        "product_collect_ms": dist([r["prod_ns"] / 1e6 for r in col]),
        "product_collect_cpu_ms": dist([r["prod_cpu_ns"] / 1e6 for r in col]),
        "attempt_ms": dist([r["elapsed_ns"] / 1e6 for r in att]),
        "attempt_cpu_ms": dist([r["cpu_ns"] / 1e6 for r in att]),
        "sample_duration_ms": dist([r["duration_ns"] / 1e6 for r in att]),
        "actual_interval_ms": dist(gaps),
        "start_delay_ms": dist([g - interval_ms for g in gaps]),
        "overrun_count": sum(1 for r in att if r["elapsed_ns"] / 1e6 > interval_ms),
        "rss_start": s["start"]["rss_bytes"], "rss_end": s["end"]["rss_bytes"],
        "pss_start": s["start"]["smaps"].get("pss_bytes"), "pss_end": s["end"]["smaps"].get("pss_bytes"),
        "maxrss_kib": s["end"]["self"]["ru_maxrss"], "rss_slope_kib_per_min": (lambda v: v and v / 1024)(
            slope_per_min([(r["t"], r["rss_bytes"]) for r in mem])),
        "buffer_bytes": s["buffer_bytes"],
        "ctx_voluntary": en["ru_nvcsw"] - st["ru_nvcsw"], "ctx_involuntary": en["ru_nivcsw"] - st["ru_nivcsw"],
        "minor_faults": en["ru_minflt"] - st["ru_minflt"], "major_faults": en["ru_majflt"] - st["ru_majflt"],
        "requests": len(http), "http_errors": sum(1 for r in http if r["code"] != 200),
        "response_bytes": dist([r["bytes"] for r in http]),
        "handler_ms": dist([r["elapsed_ns"] / 1e6 for r in http]),
        "handler_cpu_ms": dist([r["cpu_ns"] / 1e6 for r in http]),
        "read_cpu_ms": dist([r["read_cpu_ns"] / 1e6 for r in http]),
        "distinct_sequences_served": len({r["sequence"] for r in http}),
        "client_latency_ms": dist([r["latency_ns"] / 1e6 for r in lat]),
        "client_requests": len(lat), "client_failures": sum(1 for r in lat if r["status"] != 200),
        "client_cpu_s": sum(c["rusage"]["ru_utime"] + c["rusage"]["ru_stime"] for c in rec.get("clients", [])),
        "passive_io": s["passive_io"], "scope": s["scope"], "python": s["python"], "source_hash": s["source_hash"],
        "bench_hash": s["bench_hash"], "temps_before": rec["before"]["temps_mC"], "temps_after": rec["after"]["temps_mC"],
        "throttled_before": rec["before"].get("throttled"), "throttled_after": rec["after"].get("throttled"),
        "freq_before": rec["before"]["cpufreq_khz"], "freq_after": rec["after"]["cpufreq_khz"],
    }


def mismatches(runs):
    """Why runs compared as B0 vs B1 are not comparable (empty if they are)."""
    keys = ("alias", "interval_s", "clients", "poll_s", "python", "source_hash", "bench_hash", "scope")
    out = []
    for k in keys:
        values = {json.dumps(r[k], sort_keys=True) for r in runs}
        if len(values) > 1:
            out.append(f"{k} differs: {sorted(values)}")
    return out


def compare(runs):
    """B1 - B0 of one condition, from per-run values; 'indistinguishable' when the difference is not larger
    than the spread between repeats of the same variant (or there are no repeats to tell)."""
    valid = [r for r in runs if r["valid"]]
    b0 = [r["cpu_pct_one_core"] for r in valid if r["variant"] == "B0"]
    b1 = [r["cpu_pct_one_core"] for r in valid if r["variant"] == "B1"]
    if not b0 or not b1:
        return {"b0": b0, "b1": b1, "delta_pp": None, "verdict": "insufficient", "problems": mismatches(valid)}
    delta = sum(b1) / len(b1) - sum(b0) / len(b0)  # kept negative if negative
    spread = max(max(b0) - min(b0), max(b1) - min(b1))
    repeats = len(b0) > 1 and len(b1) > 1
    return {"b0": b0, "b1": b1, "delta_pp": delta, "spread_pp": spread if repeats else None,
            "distinguishable": repeats and abs(delta) > spread,
            "rel_pct": 100 * delta / (sum(b0) / len(b0)) if sum(b0) else None, "problems": mismatches(valid)}


def summarize_probe(rec):
    p = rec["probe"]
    t = rows(p["table"])
    periodic = [r for r in t if r["step"] < 10]
    out = {"run_id": rec["run_id"], "alias": rec["alias"], "feature": p["feature"], "period_s": p["period_s"],
           "valid": rec["valid"], "cpu_pct_one_core": p["cpu_pct_one_core"], "skipped_ticks": p["skipped_ticks"],
           "pending_at_end": p["pending_at_end"], "mounts": p["mounts"], "steps": {}}
    for step in sorted({r["step"] for r in t}):
        rs = [r for r in t if r["step"] == step]
        out["steps"][str(step)] = {"elapsed_ms": dist([r["elapsed_ns"] / 1e6 for r in rs]),
                                   "cpu_ms": dist([r["cpu_ns"] / 1e6 for r in rs]),
                                   "failures": sum(1 for r in rs if not r["ok"]),
                                   "with_value": sum(1 for r in rs if r["value_x1000"] != -10**12),
                                   "distinct_values": len({r["value_x1000"] for r in rs})}
    out["calls"] = len(periodic)
    return out


def report(a):
    recs = []
    for path in a.results:
        with open(path) as f:
            recs += [json.loads(l) for l in f if l.strip()]
    serves = [summarize_serve(r) for r in recs if r["kind"] == "run" and "serve" in r]
    groups = {}
    for s in serves:
        groups.setdefault((s["alias"], s["phase"], s["interval_s"], s["clients"], s["poll_s"]), []).append(s)
    out = {"manifests": [r for r in recs if r["kind"] == "manifest"],
           "skipped": [{"run_id": r["run_id"], "cond": r["cond"], "why": r.get("skipped") or r.get("invalid")}
                       for r in recs if r["kind"] == "run" and not r.get("valid")],
           "runs": serves,
           "comparisons": [{"key": list(k), **compare(v)} for k, v in groups.items()],
           "probes": [summarize_probe(r) for r in recs if r["kind"] == "run" and "probe" in r]}
    json.dump(out, sys.stdout, indent=1, default=str)
    print()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--variant", choices=("B0", "B1"), required=True)
    s.add_argument("--interval", type=float, required=True)
    s.add_argument("--warmup", type=float, default=30)
    s.add_argument("--measure", type=float, default=120)
    s.add_argument("--port", type=int, default=19798)
    s.add_argument("--expect-rps", type=float, default=1)
    s.add_argument("--run-id", default="manual")
    s.add_argument("--out", required=True)
    c = sub.add_parser("client")
    c.add_argument("--url", required=True)
    c.add_argument("--period", type=float, default=1.0)
    c.add_argument("--duration", type=float, required=True)
    c.add_argument("--out", required=True)
    pr = sub.add_parser("probe")
    pr.add_argument("--feature", choices=("noop", "wireless", "statvfs"), required=True)
    pr.add_argument("--period", type=float, required=True)
    pr.add_argument("--duration", type=float, default=120)
    pr.add_argument("--burst", type=int, default=0)
    pr.add_argument("--run-id", default="manual")
    pr.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--alias", required=True)
    r.add_argument("--phase", choices=("matrix", "clients", "final", "probes"), required=True)
    r.add_argument("--intervals", default="1,2,0.5,5")
    r.add_argument("--final", type=float)
    r.add_argument("--warmup", type=float, default=30)
    r.add_argument("--measure", type=float, help="override every window length (smoke tests only)")
    r.add_argument("--port", type=int, default=19798)
    r.add_argument("--budget-min", type=float, default=90)
    r.add_argument("--max-windows", type=int, default=32)
    r.add_argument("--watch-url", help="a running service that must keep answering between runs")
    r.add_argument("--source-sha", default="unknown")
    rp = sub.add_parser("report")
    rp.add_argument("results", nargs="+")
    a = p.parse_args(argv)
    {"serve": serve, "client": client, "probe": probe, "run": run, "report": report}[a.cmd](a)


if __name__ == "__main__":
    main()
