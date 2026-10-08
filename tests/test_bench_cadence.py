"""The bench tools' own arithmetic and bookkeeping (benchmarks/). No performance thresholds: those are judged
from recorded device runs, not on CI."""
import json
import subprocess
import sys
import time

import pytest

from benchmarks import cadence
from benchmarks.passive import Passive, parse_diskstats, parse_net_dev, parse_psi

NET = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: {lo} 10 0 0 0 0 0 0 {lo} 10 0 0 0 0 0 0
  eth0: {eth} 20 0 0 0 0 0 0 500 5 0 0 0 0 0 0
"""
DISK = """ 179 0 mmcblk0 {r} 0 {s} 0 10 0 80 0 0 {io} 0 0 0 0 0 0 0
 179 1 mmcblk0p1 5 0 40 0 0 0 0 0 0 0 0 0 0 0 0 0 0
   7 0 loop0 1 0 2 0 0 0 0 0 0 0 0 0 0 0 0 0 0
"""
PSI = "some avg10=1.50 avg60=0.00 avg300=0.00 total={some}\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


@pytest.fixture
def fake(tmp_path):
    (tmp_path / "proc/net").mkdir(parents=True)
    (tmp_path / "proc/pressure").mkdir()
    (tmp_path / "sys/class/net/eth0/device").mkdir(parents=True)
    (tmp_path / "sys/class/net/lo").mkdir()
    (tmp_path / "sys/block/mmcblk0").mkdir(parents=True)
    (tmp_path / "sys/block/loop0").mkdir()

    def write(lo=0, eth=1000, r=10, s=100, io=0, some=None):
        (tmp_path / "proc/net/dev").write_text(NET.format(lo=lo, eth=eth))
        (tmp_path / "proc/diskstats").write_text(DISK.format(r=r, s=s, io=io))
        if some is not None:
            (tmp_path / "proc/pressure/cpu").write_text(PSI.format(some=some))
    clock = Clock()
    return Passive(str(tmp_path / "proc"), str(tmp_path / "sys"), clock), write, clock


def test_parsers():
    assert parse_net_dev(NET.format(lo=1, eth=2))["eth0"] == (2, 20, 500, 5)
    d = parse_diskstats(DISK.format(r=1, s=2, io=3))
    assert d["mmcblk0"] == (1, 2, 10, 80, 3)
    assert parse_psi(PSI.format(some=7))["some"] == {"avg10": 1.5, "total_us": 7}


def test_rates_use_observed_time_and_warmup_is_not_zero(fake):
    p, write, clock = fake
    write(eth=1000, r=10, s=100, io=0)
    first = p()
    eth = first["network"]["interfaces"]["eth0"]
    assert eth["reason"] == "warmup" and "rx_bytes_per_s" not in eth
    write(eth=3000, r=20, s=300, io=500)
    clock.t = 2_000_000_000  # 2 s observed, whatever the configured interval was
    second = p()
    eth = second["network"]["interfaces"]["eth0"]
    assert eth["rx_bytes_per_s"] == 1000 and eth["rx_bits_per_s"] == 8000 and eth["physical"]
    assert second["network"]["interfaces"]["lo"]["physical"] is False
    disk = second["disk"]["devices"]
    assert set(disk) == {"mmcblk0"}  # the partition and loop0 are not added to the disk
    assert disk["mmcblk0"]["read_bytes_per_s"] == 512 * 200 / 2 and disk["mmcblk0"]["io_time_ratio"] == 0.25


def test_counter_reset_and_removed_device(fake, tmp_path):
    p, write, clock = fake
    write(eth=5000)
    p()
    write(eth=100)
    clock.t = 1_000_000_000
    eth = p()["network"]["interfaces"]["eth0"]
    assert eth["reason"] == "counter_reset" and "rx_bytes_per_s" not in eth
    (tmp_path / "proc/net/dev").write_text("\n".join(NET.format(lo=0, eth=0).splitlines()[:3]) + "\n")
    clock.t = 2_000_000_000
    assert p()["network"]["removed"] == ["eth0"]


def test_psi_unsupported_is_not_zero(fake):
    p, write, clock = fake
    write()
    out = p()["pressure"]
    assert out["memory"] == {"state": "unsupported", "reason": "ENOENT"}
    write(some=1000)
    clock.t = 1
    p()
    write(some=501000)
    clock.t = 1_000_000_001
    cpu = p()["pressure"]["cpu"]
    assert cpu["state"] == "ok" and cpu["some"]["stall_ratio"] == 0.5 and cpu["full"]["stall_ratio"] == 0


def test_cpu_pct_is_one_core_and_keeps_sign():
    a = {"ru_utime": 1.0, "ru_stime": 0.5}
    b = {"ru_utime": 1.6, "ru_stime": 0.6}
    assert cadence.cpu_pct_one_core(a, b, 70.0) == pytest.approx(1.0)
    runs = [dict(base, variant="B0", cpu_pct_one_core=0.9), dict(base, variant="B0", cpu_pct_one_core=0.8),
            dict(base, variant="B1", cpu_pct_one_core=0.7), dict(base, variant="B1", cpu_pct_one_core=0.8)]
    c = cadence.compare(runs)
    assert c["delta_pp"] == pytest.approx(-0.1) and c["distinguishable"] is False and c["problems"] == []
    assert c["rel_pct"] == pytest.approx(-100 * 0.1 / 0.85)


base = {"valid": True, "alias": "x", "interval_s": 1.0, "clients": 1, "poll_s": 1.0, "python": "3.13",
        "source_hash": "s", "bench_hash": "b", "scope": {"interfaces": 2}}


def test_compare_flags_mismatch_and_missing_variant():
    runs = [dict(base, variant="B0", cpu_pct_one_core=1.0), dict(base, variant="B1", cpu_pct_one_core=1.2,
                                                                scope={"interfaces": 3})]
    c = cadence.compare(runs)
    assert c["problems"] and "scope" in c["problems"][0] and c["spread_pp"] is None and not c["distinguishable"]
    assert cadence.compare([dict(base, variant="B0", cpu_pct_one_core=1.0)])["verdict"] == "insufficient"


def test_percentile_and_missing_values():
    assert cadence.percentile([], 95) is None
    assert cadence.percentile(list(range(1, 101)), 95) == 95
    assert cadence.percentile([5, None, 1], 50) == 1
    assert cadence.dist([None])["n"] == 0 and cadence.dist([None])["mean"] is None


def test_table_is_fixed_size():
    t = cadence.Table(["t", "v"], 2)
    size = t.nbytes()
    for i in range(5):
        t.add(i, i * 10)
    assert t.n == 2 and t.dropped == 3 and t.nbytes() == size
    assert cadence.rows(t.dump(), 1, 2) == [{"t": 1, "v": 10}]


def test_budget_and_plan():
    assert [c["variant"] for c in cadence.plan("matrix", [1.0])] == ["B0", "B1", "B1", "B0"]
    assert cadence.plan("final", [], 5.0)[0]["measure"] == 600 and cadence.plan("final", [], 1.0)[0]["measure"] == 300
    cond = {"kind": "serve", "measure": 120}
    assert cadence.budget_left([], cond, 30, 5400, 32) is None
    assert "window" in cadence.budget_left([{"wall_s": 1}] * 32, cond, 30, 5400, 32)
    assert "time" in cadence.budget_left([{"wall_s": 5300}], cond, 30, 5400, 32)
    assert cadence.budget_left([{"wall_s": 5300, "counted": False}], cond, 30, 6000, 1) is None


def test_guard_and_throttle_bits(tmp_path):
    ok = {"mem_available": 2**30, "throttled": "throttled=0x50000"}  # sticky history bits only
    assert cadence.throttled_now(ok) == 0 and cadence.guard(ok, str(tmp_path), None) is None
    assert "throttle" in cadence.guard({**ok, "throttled": "throttled=0x50005"}, str(tmp_path), None)
    assert cadence.throttled_now({"mem_available": 1}) is None
    assert "memory" in cadence.guard({"mem_available": 1}, str(tmp_path), None)


def test_wireless_and_mounts():
    text = "Inter-| sta-|\n face | tus |\n wlan0: 0000   44.  -66.  -256  0 0 0 0 0 0\n"
    assert cadence.parse_wireless(text) == {"wlan0": -66.0}
    info = ("22 1 179:2 / / rw - ext4 /dev/mmcblk0p2 rw\n"
            "23 1 0:5 / /proc rw - proc proc rw\n"
            "24 1 0:40 / /mnt/nas rw - nfs4 nas:/x rw\n"
            "25 1 0:41 / /mnt/my\\040disk rw - fuseblk /dev/sdb1 rw\n"
            "26 1 8:1 / /boot/firmware rw - vfat /dev/mmcblk0p1 rw\n")
    assert cadence.local_mounts(info) == ["/", "/boot/firmware"]


def test_report_roundtrip(tmp_path, capsys):
    """A short real serve run: the report reads it back with warmup excluded and the same numbers again."""
    out = tmp_path / "s.json"
    cadence.main(["serve", "--variant", "B1", "--interval", "0.1", "--warmup", "0.3", "--measure", "0.6",
                  "--port", "0", "--out", str(out)])
    serve = json.loads(out.read_text())
    rec = {"kind": "run", "run_id": "r", "alias": "t", "valid": True, "order": 0, "serve": serve,
           "cond": {"phase": "matrix", "clients": 0, "poll": 1.0}, "before": {"temps_mC": {}, "cpufreq_khz": {}},
           "after": {"temps_mC": {}, "cpufreq_khz": {}}}
    results = tmp_path / "results.jsonl"
    results.write_text(json.dumps(rec) + "\n")
    capsys.readouterr()
    cadence.main(["report", str(results)])
    first = capsys.readouterr().out
    cadence.main(["report", str(results)])
    assert capsys.readouterr().out == first
    run = json.loads(first)["runs"][0]
    assert 0.5 < run["measured_elapsed_s"] < 1.5 and run["measured_elapsed_s"] == serve["measured_elapsed_s"]
    all_attempts = len(serve["tables"]["attempt"]["rows"])
    assert 0 < run["sample_count"] < all_attempts  # warmup attempts are not counted
    assert run["passive_ms"]["n"] > 0 and run["scope"]["interfaces"] > 0
    cadence.main(["report", "--md", str(results)])
    md = capsys.readouterr().out
    assert "| t | matrix | 0.1 |" in md and "| B1 |" in md


FAKE = r'''
import json, os, sys, time
args = sys.argv[1:]
out = args[args.index("--out") + 1]
mode = os.environ["FAKE_MODE"]
if args[0] == "client":
    json.dump({"rusage": {}, "table": {"fields": ["t"], "rows": []}}, open(out, "w"))
elif args[0] == "probe":
    json.dump({"pending_at_end": mode == "pending", "skipped_ticks": 3 if mode == "pending" else 0}, open(out, "w"))
elif mode == "silent":
    time.sleep(60)  # alive, stdout open, never ready
elif mode == "unsupported":
    print("unsupported: profile modes unsupported here", flush=True)
    sys.exit(3)
elif mode == "partial":
    sys.stdout.write("rea")  # part of the ready line, no newline, then stays alive
    sys.stdout.flush()
    time.sleep(60)
else:
    print("ready", flush=True)
    if mode == "hang":
        time.sleep(60)
    elif mode == "ok":
        json.dump({"clock_jump": False}, open(out, "w"))
    # mode "noresult": exits 0 without writing a result
'''


@pytest.fixture
def fake_child(tmp_path, monkeypatch):
    script = tmp_path / "fake_child.py"
    script.write_text(FAKE)
    started = []
    real = subprocess.Popen

    def popen(*args, **kw):
        started.append(real(*args, **kw))
        return started[-1]
    monkeypatch.setattr(cadence, "child_cmd", lambda me, *args: [me, str(script), *args])
    monkeypatch.setattr(cadence.subprocess, "Popen", popen)
    args = type("A", (), {"out": str(tmp_path), "warmup": 0.0, "port": 1, "ready_timeout": 0.5})()

    def execute(mode, **cond):
        monkeypatch.setenv("FAKE_MODE", mode)
        c = {"kind": "serve", "variant": "B0", "interval": 1.0, "clients": 1, "poll": 1.0, "measure": 0.1, **cond}
        return cadence.execute(sys.executable, "r", c, args)
    return execute, started, real


def test_execute_normal_path(fake_child):
    execute, started, real = fake_child
    out = execute("ok")
    assert out["valid"] and out["serve"] == {"clock_jump": False} and len(out["clients"]) == 1


def test_execute_server_never_ready_is_bounded_and_reaped(fake_child):
    execute, started, real = fake_child
    t0 = time.monotonic()
    out = execute("silent")
    assert time.monotonic() - t0 < 15 and not out["valid"] and "not ready" in out["invalid"]
    assert "timeout" not in out and all(p.poll() is not None for p in started)


def test_execute_timeout_kills_and_reaps(fake_child, monkeypatch):
    execute, started, real = fake_child
    monkeypatch.setattr(real, "wait", _short_wait(real.wait))
    out = execute("hang")
    assert out["timeout"] and "server timeout" in out["invalid"] and "unreaped" not in out
    assert all(p.poll() is not None for p in started)


def _short_wait(wait):
    """Popen.wait with the runner's long deadlines cut to 1 s, so a hanging child times out quickly."""
    def short(self, timeout=None):
        return wait(self, timeout=None if timeout is None else min(timeout, 1.0))
    return short


def test_execute_child_without_result_does_not_raise(fake_child):
    execute, _, _ = fake_child
    out = execute("noresult")
    assert not out["valid"] and "no result" in out["invalid"]


def test_unreaped_process_is_reported():
    class Stuck:
        pid = 42

        def poll(self):
            return None

        def kill(self):
            pass

        def wait(self, timeout=None):
            raise cadence.subprocess.TimeoutExpired("x", timeout)
    out = cadence.failed("server timeout", [Stuck()], timeout=True)
    assert out["timeout"] and out["unreaped"] == [42] and "still running" in out["invalid"]


def test_pending_probe_is_not_valid(fake_child):
    execute, _, _ = fake_child
    out = execute("pending", kind="probe", feature="statvfs", period=30.0)
    assert out["valid"] is False and out["incomplete"] and out["probe"]["skipped_ticks"] == 3
    assert execute("done", kind="probe", feature="statvfs", period=30.0)["valid"]


def test_pooled_p95_differs_from_max_of_per_run_p95():
    def rec(values):
        rows = [[i, 0, 0, int(v * 1e6), 0] for i, v in enumerate(values, 1)]
        return {"valid": True, "serve": {"variant": "B1", "start": {"mono": 0}, "end": {"mono": 10**9},
                "tables": {"collect": {"fields": ["t", "prod_ns", "prod_cpu_ns", "passive_ns", "passive_cpu_ns"],
                                       "rows": rows},
                           "attempt": {"fields": ["t", "elapsed_ns"], "rows": []}}}}
    p = cadence.pooled([rec([1] * 94 + [100] * 6), rec([2] * 100)])["B1"]
    assert p["runs"] == 2 and p["passive_ms"]["n"] == 200
    assert p["passive_ms"]["p95"] == 2 and p["passive_ms"]["per_run_max_p95"] == 100


def test_pending_and_skipped_reach_the_report():
    probe = {"feature": "statvfs", "period_s": 30.0, "cpu_pct_one_core": 0.1, "skipped_ticks": 3,
             "pending_at_end": True, "mounts": 1,
             "table": {"fields": ["t", "step", "elapsed_ns", "cpu_ns", "count", "value_x1000", "ok"],
                       "rows": [[1, 0, 10**6, 10**6, 1, -10**12, 1]]}}
    rec = {"run_id": "r", "alias": "x", "valid": False, "invalid": "a probe call was still running at the end",
           "probe": probe}
    s = cadence.summarize_probe(rec)
    assert s["skipped_ticks"] == 3 and s["pending_at_end"] and not s["valid"]
    md = cadence.markdown({"comparisons": [], "runs": [], "probes": [s], "skipped": []})
    assert "| 3/True | no: a probe call was still running at the end |" in md


WRITER = r'''
import os, sys, time
# argv: pieces of stdout, each "<delay s>:<text>"; then stays alive with stdout open until killed
for piece in sys.argv[1:]:
    delay, text = piece.split(":", 1)
    time.sleep(float(delay))
    os.write(1, text.encode().replace(b"\\n", b"\n"))
time.sleep(30)
'''


@pytest.fixture
def writer(tmp_path):
    script = tmp_path / "writer.py"
    script.write_text(WRITER)
    procs = []

    def start(*pieces):
        procs.append(subprocess.Popen([sys.executable, str(script), *pieces], stdout=subprocess.PIPE))
        return procs[-1]
    yield start
    for p in procs:
        assert cadence.stop_process(p)
        p.stdout.close()


def timed(fn):
    t0 = time.monotonic()
    out = fn()
    return out, time.monotonic() - t0


# The child's start-up (an interpreter launch) happens before its first delay, so every deadline below
# leaves it time: timeouts are 2 s and more, the quiet periods well past them.

def test_wait_line_no_output_times_out(writer):
    out, took = timed(lambda: cadence.wait_line(writer(), 2.0))
    assert out is None and 1.9 < took < 4


def test_wait_line_partial_line_does_not_block(writer):
    p = writer("0:rea", "6:dy\\n")  # no newline within the deadline
    out, took = timed(lambda: cadence.wait_line(p, 2.0))
    assert out is None and took < 4


def test_wait_line_pieces_within_deadline(writer):
    p = writer("0:re", "0.2:ad", "0.2:y 1\\nmore")
    assert cadence.wait_line(p, 5.0) == "ready 1\n"


def test_wait_line_trickle_does_not_extend_deadline(writer):
    p = writer(*["0.3:x"] * 30)  # a byte every 0.3 s, never a newline
    out, took = timed(lambda: cadence.wait_line(p, 2.0))
    assert out is None and took < 4


def test_wait_line_eof_without_newline(tmp_path):
    p = subprocess.Popen([sys.executable, "-c", "import os; os.write(1, b'ready')"], stdout=subprocess.PIPE)
    try:
        assert cadence.wait_line(p, 5.0) is None
    finally:
        assert cadence.stop_process(p)
        p.stdout.close()


def test_execute_partial_ready_is_bounded_and_reaped(fake_child, monkeypatch):
    execute, started, _ = fake_child
    out, took = timed(lambda: execute("partial"))
    assert not out["valid"] and "not ready" in out["invalid"] and took < 15
    assert all(p.poll() is not None for p in started)


def test_execute_unsupported_mode_is_not_a_measurement(fake_child):
    execute, started, _ = fake_child
    out = execute("unsupported")
    assert out["valid"] is False and out["unsupported"] and "unsupported" in out["invalid"]
    assert "timeout" not in out and all(p.poll() is not None for p in started)
