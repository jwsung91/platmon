"""The bench tools' own arithmetic and bookkeeping (benchmarks/). No performance thresholds: those are judged
from recorded device runs, not on CI."""
import json

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
