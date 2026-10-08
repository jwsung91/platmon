"""The stage recorder of benchmarks/breakdown.py: its arithmetic, its threads, and that wrapping the product
in place neither changes what it does nor stays behind. No performance thresholds."""
import copy
import json
import threading

import pytest

import collector
from benchmarks import breakdown, cadence
from collector import common, sampler, sysfs
from collector.sampler import Sampler, pick_clock
from frontends import server


class FakeClock:
    """Both clocks of the recorder; the timed functions advance it."""

    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(breakdown, "mono", c)
    monkeypatch.setattr(breakdown, "tcpu", c)
    return c


def recorder(capacity=100):
    rec = breakdown.Recorder(cadence.Table)
    rec.allocate(capacity, capacity)
    return rec


def rows(rec):
    d = rec.dump()
    out = {}
    for r in cadence.rows(d["rows"]):
        out[d["names"][r["name"]]] = r
    return out


def test_nested_inclusive_and_self_do_not_overlap(clock):
    rec = recorder()

    def inner():
        clock.t += 5

    inner = rec.wrap("inner", inner)

    def outer():
        clock.t += 3
        inner()
        inner()

    outer = rec.wrap("outer", outer)
    begun = rec.begin()
    outer()
    rec.end("collection", begun)
    r = rows(rec)
    assert (r["outer"]["calls"], r["outer"]["incl_cpu_ns"], r["outer"]["self_cpu_ns"]) == (1, 13, 3)
    assert (r["inner"]["calls"], r["inner"]["incl_cpu_ns"], r["inner"]["self_cpu_ns"]) == (2, 10, 10)
    unit = cadence.rows(rec.dump()["units"])[0]
    assert unit["cpu_ns"] == 13 and unit["wrapped_calls"] == 3 and unit["kind"] == breakdown.KINDS["collection"]


def test_recursion_counts_the_outermost_call_only(clock):
    rec = recorder()

    def walk(n):
        clock.t += 1
        return n if n == 0 else walk(n - 1)

    walk = rec.wrap("walk", walk)
    begun = rec.begin()
    assert walk(4) == 0
    rec.end("collection", begun)
    r = rows(rec)["walk"]
    assert r["calls"] == 1 and r["incl_cpu_ns"] == 5 and r["self_cpu_ns"] == 5


def test_wrapper_calls_once_and_passes_results_and_exceptions():
    rec = recorder()
    calls = []

    def fn(x, y=0):
        calls.append(x)
        if x < 0:
            raise KeyError(x)
        return x + y

    w = rec.wrap("fn", fn)
    begun = rec.begin()
    assert w(1, y=2) == 3
    with pytest.raises(KeyError):
        w(-1)
    rec.end("collection", begun)
    assert calls == [1, -1] and rows(rec)["fn"]["calls"] == 2


def test_threads_keep_their_own_units():
    rec = recorder()
    gate = threading.Barrier(2)
    w = rec.wrap("work", lambda: None)

    def unit(n):
        begun = rec.begin()
        gate.wait()  # both units open at once
        for _ in range(n):
            w()
        gate.wait()
        rec.end("request", begun)

    threads = [threading.Thread(target=unit, args=(n,)) for n in (3, 7)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    d = rec.dump()
    assert sorted(r["calls"] for r in cadence.rows(d["rows"])) == [3, 7]
    assert len({u["unit"] for u in cadence.rows(d["units"])}) == 2


def test_buffers_are_bounded():
    rec = recorder(capacity=2)
    w = rec.wrap("w", lambda: None)
    for _ in range(3):
        begun = rec.begin()
        w()
        rec.end("listener", begun)
    d = rec.dump()
    assert len(d["units"]["rows"]) == 2 and d["units"]["dropped"] == 1 and d["rows"]["dropped"] == 1


def test_install_reaches_from_imported_call_sites_and_restores(capsys):
    originals = {"collect": common.collect, "entries": common.entries, "read": common.read,
                 "group_read": sysfs.Group.__dict__["read"], "copy": sampler.copy, "json": server.json,
                 "shutil": common.shutil, "sample": common.CpuCounters.__dict__["sample"]}
    rec = recorder(1000)
    with breakdown.install(rec):
        begun = rec.begin()
        collector.collect()
        sampler.copy.deepcopy({"a": [{"b": 1}, {"c": [2, 3]}]})  # recursive inside: one call
        assert server.json.dumps({"x": 1}) == json.dumps({"x": 1})
        rec.end("collection", begun)
    r = rows(rec)
    for name in ("common.collect", "common.thermal_zones", "common.hwmon_sensors", "common.meminfo",
                 "common.disk_usage", "common.read (uptime, model, os-release)", "common.cpu_sample",
                 "work.entries", "collect._collect", "collect.summarize"):
        assert r[name]["calls"] >= 1, name
    assert r["deepcopy"]["calls"] == 1 and r["json.dumps"]["calls"] == 1
    assert (common.collect, common.entries, common.read, sysfs.Group.__dict__["read"], sampler.copy, server.json,
            common.shutil, common.CpuCounters.__dict__["sample"]) == tuple(originals.values())
    assert sampler.copy is copy and server.json is json
    assert capsys.readouterr().out == ""  # nothing of the bench on stdout


def test_install_restores_after_an_exception():
    with pytest.raises(RuntimeError):
        with breakdown.install(recorder()):
            raise RuntimeError
    assert sampler.copy is copy and not hasattr(common.collect, "__wrapped_stage__")


def test_product_output_and_reads_are_the_same_with_stages(monkeypatch):
    """Same reads (paths, in order), same keys, source ids and collector states; provenance still checks out."""
    paths = []
    plain_read = sysfs.Group.read

    def counting(self, path, *args, **kwargs):
        paths.append(path)
        return plain_read(self, path, *args, **kwargs)
    monkeypatch.setattr(sysfs.Group, "read", counting)

    def once(staged):
        paths.clear()
        clock = pick_clock()
        cpu = common.CpuCounters(clock[0])
        collect = lambda: collector.collect_recorded(cpu, {}, clock[0])  # noqa: E731
        s = Sampler(collect, 1.0, clock=clock)
        rec = recorder(1000)
        ctx = breakdown.install(rec) if staged else breakdown.contextlib.nullcontext()
        with ctx:
            s._attempt()
            s._attempt()  # the second collection has CPU rows, clocks and their records
            stats = s.read()[0]
        return stats, list(paths)

    plain, plain_paths = once(False)
    staged, staged_paths = once(True)

    def split(ps):  # which cores have a usage (and so a clock read) depends on the ticks between readings
        return [p for p in ps if "/cpufreq/" not in p], sum("/cpufreq/" in p for p in ps)
    assert split(staged_paths)[0] == split(plain_paths)[0]
    assert split(staged_paths)[1] == len(staged["cpu"]) and split(plain_paths)[1] == len(plain["cpu"])
    assert set(staged) == set(plain)

    def ids(stats):  # CPU clock records by core id: the row position depends on which cores had ticks
        meta = stats.get("sensor_meta", {})
        out = {k: v["id"] for k, v in meta.items() if not k.startswith("/cpu/")}
        for i, row in enumerate(stats["cpu"]):
            if f"/cpu/{i}/freq" in meta:
                out[f"cpu {row['id']}"] = meta[f"/cpu/{i}/freq"]["id"]
        return out
    common_cores = {f"cpu {r['id']}" for r in staged["cpu"]} & {f"cpu {r['id']}" for r in plain["cpu"]}
    a, b = ids(staged), ids(plain)
    assert {k: v for k, v in a.items() if not k.startswith("cpu ") or k in common_cores} == \
        {k: v for k, v in b.items() if not k.startswith("cpu ") or k in common_cores}
    assert ({k: v["state"] for k, v in staged["collectors"].items()}
            == {k: v["state"] for k, v in plain["collectors"].items()})
    assert staged["sample"]["data_age_basis"] == plain["sample"]["data_age_basis"]


def serve_result(units, rows_, names, t0=100, t1=200, elapsed=1.0, cpu=(0.0, 0.5)):
    return {"measured_elapsed_s": elapsed, "start": {"mono": t0, "self": {"ru_utime": cpu[0], "ru_stime": 0}},
            "end": {"mono": t1, "self": {"ru_utime": cpu[1], "ru_stime": 0}},
            "breakdown": {"names": names,
                          "rows": {"fields": ["unit", "name", "calls", "incl_ns", "incl_cpu_ns", "self_cpu_ns"], "rows": rows_},
                          "units": {"fields": ["t", "end", "kind", "unit", "cpu_ns", "thread_cpu_ns", "wrapped_calls"],
                                    "rows": units}}}


def test_stage_table_uses_window_units_only():
    names = ["a"]
    units = [[50, 60, 0, 1, 10**8, 0, 1],      # warmup: left out
             [120, 130, 0, 2, 10**8, 0, 1],
             [190, 250, 0, 3, 10**8, 0, 1],     # starts inside, ends after the window
             [150, 160, 1, 4, 10**7, 3 * 10**7, 1]]
    rows_ = [[1, 0, 1, 9 * 10**6, 10**8, 10**8], [2, 0, 2, 4 * 10**6, 4 * 10**6, 3 * 10**6],
             [3, 0, 2, 2 * 10**6, 2 * 10**6, 10**6]]
    s = serve_result(units, rows_, names)
    table, n = breakdown.stage_table([s], "collection")
    assert n == 2
    a = table[0]
    assert a["calls_per_unit"] == 2 and a["cpu_ms_per_unit"] == 3 and a["self_cpu_ms_per_unit"] == 2
    assert a["cpu_pct_one_core"] == pytest.approx(0.6) and a["units_with_stage"] == 2
    acc = breakdown.accounting(s)
    assert acc["parts"]["collection"] == {"units": 2, "straddling": 1, "cpu_s": 0.2}
    assert acc["parts"]["request"]["cpu_s"] == 0.03  # the worker thread's whole CPU, not cpu_ns
    assert acc["unattributed_cpu_s"] == pytest.approx(0.5 - 0.23)


def test_negative_unattributed_is_kept():
    s = serve_result([[120, 130, 0, 1, 9 * 10**8, 0, 0]], [], [], cpu=(0.0, 0.5))
    assert breakdown.accounting(s)["unattributed_cpu_s"] == pytest.approx(-0.4)


def test_wrapper_cost_is_measured():
    c = breakdown.wrapper_cost(n=2000)
    assert c["calls"] == 2000 and c["clock_calls_per_wrapped_call"] == 4


def test_profiles_merge_per_thread():
    p = breakdown.Profiles()
    with p.profiled():  # off: nothing recorded
        sum(range(10))
    p.on.set()

    def work():
        with p.profiled():
            sorted(range(1000), key=lambda x: -x)
    threads = [threading.Thread(target=work) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    r = p.report(top=5)
    assert r["units"] == 2 and "thread_time_ns" in r["timer"] and "sorted by tottime" in r["text"]
