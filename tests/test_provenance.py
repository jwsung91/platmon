"""Sensor source ids, read spans and the read-based data age (sensor_meta, sample.data_age_basis).
Fake sysfs trees with real symlinks and a fake elapsed clock; nothing on the host is read for sensors."""
import functools
import io
import json
import os
import subprocess
import sys

import pytest

import collector
from collector import common, jetson, sysfs
from collector.common import CpuCounters
from collector.sampler import Collected, Sampler
from test_common import Proc, idle_busy
from test_sampler import Clock, fake


class Tick:
    """Elapsed clock that moves 1 µs on every call, so each read gets its own start and end."""

    def __init__(self):
        self.ns = 10**12

    def __call__(self):
        self.ns += 1000
        return self.ns


def chip(sysroot, device, n, files):
    """A hwmon chip at <sysroot>/<device>/hwmon/hwmon<n>, linked from class/hwmon like the kernel does."""
    d = sysroot / device / "hwmon" / f"hwmon{n}"
    d.mkdir(parents=True)
    for name, value in files.items():
        (d / name).write_text(str(value))
    link = sysroot / "class" / "hwmon" / f"hwmon{n}"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(d, link.parent))
    return d


def zone(sysroot, n, type_, temp):
    d = sysroot / "devices" / "virtual" / "thermal" / f"thermal_zone{n}"
    d.mkdir(parents=True)
    (d / "type").write_text(type_)
    (d / "temp").write_text(str(temp))
    link = sysroot / "class" / "thermal" / f"thermal_zone{n}"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(d, link.parent))


def traced(*names, clock=None):
    return sysfs.groups(*names, trace=sysfs.Trace(clock or Tick()))


def hwmon(sysroot, clock=None):
    g = traced("temperature", "power", "fans", clock=clock)
    out = common.hwmon_sensors(root=str(sysroot / "class" / "hwmon"), groups=g)
    return out, g


CHIP = {"name": "ina", "temp1_input": 40000, "temp1_label": "Board", "power1_input": 2000000, "power1_label": "VIN",
        "in2_label": "VDD", "in2_input": 5000, "curr2_input": 1000, "fan1_input": 900, "pwm1": 128}


# ---------- source identity ----------

def test_descriptor_id_is_fixed():
    """sha256 of a sorted, compact JSON descriptor: the same in any process and hash seed."""
    expected = "src1:dc1e592a9185fe57929e05c59a5759c4bb2cdd10e04a85525241df68d9a80bd0"
    src = sysfs.source("hwmon", "celsius", "device_channel", device="devices/platform/i2c/1-0040", attr="temp1_input")
    assert src == {"id": expected, "provider": "hwmon", "identity_basis": "device_channel", "unit": "celsius"}
    code = ("from collector import sysfs; print(sysfs.source('hwmon', 'celsius', 'device_channel', "
            "device='devices/platform/i2c/1-0040', attr='temp1_input')['id'])")
    for seed in ("0", "12345"):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                             env=dict(os.environ, PYTHONHASHSEED=seed), cwd=os.path.dirname(os.path.dirname(__file__)))
        assert out.stdout.strip() == expected
    assert sysfs.source("hwmon", "celsius", "unresolved") == {
        "id": None, "provider": "hwmon", "identity_basis": "unresolved", "unit": "celsius"}


def test_label_change_keeps_id_and_channels_differ(tmp_path):
    d = chip(tmp_path, "devices/platform/i2c/1-0040", 3, CHIP)
    (_, power, _), g = hwmon(tmp_path)
    first = {k: v["id"] for k, v in g["temperature"].sensors.items()}
    assert list(first) == ["ina Board"]
    (d / "temp1_label").write_text("Renamed")
    _, g2 = hwmon(tmp_path)
    assert {k: v["id"] for k, v in g2["temperature"].sensors.items()} == {"ina Renamed": first["ina Board"]}
    ids = [g["power"].sensors["VIN"]["id"], g["power"].sensors["VDD"]["id"], first["ina Board"]]
    fan = [v["id"] for v in g["fans"].sensors.values()]
    assert len(set(ids + fan)) == 5  # temp, direct power, computed power, rpm, pwm: all different
    assert g["power"].sensors["VIN"]["identity_basis"] == "device_channel"


def test_same_name_on_two_devices_differs(tmp_path):
    chip(tmp_path, "devices/platform/i2c/1-0040", 1, {"name": "nvme", "temp1_input": 40000, "temp1_label": "Composite"})
    chip(tmp_path, "devices/platform/i2c/1-0041", 2, {"name": "nvme", "temp1_input": 41000, "temp1_label": "Composite"})
    (temps, _, _), g = hwmon(tmp_path)
    assert list(temps) == ["nvme Composite", "nvme Composite (hwmon2)"]
    a, b = (g["temperature"].sensors[k]["id"] for k in temps)
    assert a != b


def test_renumbered_hwmon_keeps_device_id(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"  # also: different access prefixes give the same ids
    chip(a, "devices/platform/i2c/1-0040", 3, CHIP)
    chip(b, "devices/platform/i2c/1-0040", 7, CHIP)  # same device, enumerated as hwmon7 this time
    _, ga = hwmon(a)
    _, gb = hwmon(b)
    for name in ("temperature", "power"):
        assert {k: v["id"] for k, v in ga[name].sensors.items()} == {k: v["id"] for k, v in gb[name].sensors.items()}


def test_two_hwmon_nodes_on_one_device_are_not_merged(tmp_path):
    chip(tmp_path, "devices/platform/i2c/1-0040", 1, {"name": "x", "temp1_input": 40000})
    chip(tmp_path, "devices/platform/i2c/1-0040", 2, {"name": "y", "temp1_input": 41000})
    (temps, _, _), g = hwmon(tmp_path)
    infos = [g["temperature"].sensors[k] for k in temps]
    assert [i["identity_basis"] for i in infos] == ["resolved_path", "resolved_path"]  # the device alone is ambiguous
    assert infos[0]["id"] != infos[1]["id"]


def test_virtual_hwmon_and_thermal_zone_are_path_based(tmp_path):
    chip(tmp_path, "devices/virtual", 0, {"name": "acpitz", "temp1_input": 30000})
    zone(tmp_path, 0, "cpu-thermal", 51000)
    _, g = hwmon(tmp_path)
    assert g["temperature"].sensors["acpitz temp1"]["identity_basis"] == "resolved_path"  # not "devices/virtual"
    tg = sysfs.Group("temperature", sysfs.Trace(Tick()))
    temps, _ = common.thermal_zones(root=str(tmp_path / "class" / "thermal"), group=tg)
    assert temps == {"cpu": 51.0}
    assert tg.sensors["cpu"]["provider"] == "thermal" and tg.sensors["cpu"]["identity_basis"] == "resolved_path"


def test_class_alias_and_device_path_resolve_alike(tmp_path):
    d = chip(tmp_path, "devices/platform/i2c/1-0040", 3, CHIP)
    via_class = sysfs.canonical(str(tmp_path / "class" / "hwmon" / "hwmon3" / "temp1_input"), str(tmp_path))
    assert via_class == sysfs.canonical(str(d / "temp1_input"), str(tmp_path)) == \
        "devices/platform/i2c/1-0040/hwmon/hwmon3/temp1_input"
    assert sysfs.canonical(str(tmp_path / "missing"), str(tmp_path)) is None
    assert sysfs.canonical("/etc/hostname", str(tmp_path)) is None  # outside the sysfs root


def test_unresolved_source_keeps_the_value(tmp_path, monkeypatch):
    chip(tmp_path, "devices/platform/i2c/1-0040", 3, CHIP)
    monkeypatch.setattr(sysfs, "canonical", lambda path, root: None)
    (temps, power, fans), g = hwmon(tmp_path)
    assert temps == {"ina Board": 40.0} and power == {"VIN": 2.0, "VDD": 5.0} and fans[0]["rpm"] == 900
    assert {v["identity_basis"] for v in g["temperature"].sensors.values()} == {"unresolved"}
    assert g["temperature"].sensors["ina Board"]["id"] is None and g["temperature"].sensors["ina Board"]["span"]
    assert g["temperature"].status()["state"] == "ok"  # no id is not a read error


def test_gpu_sources_follow_the_file_used(tmp_path):
    def gpu_tree(root, files):
        for path, value in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(str(value))

    gpu_tree(tmp_path / "a", {"class/devfreq/17000000.gpu/device/load": 500, "class/devfreq/17000000.gpu/cur_freq": 1})
    gpu_tree(tmp_path / "b", {"devices/platform/gpu.0/load": 500})  # another BSP: another source
    ga, gb = sysfs.Group("gpu", sysfs.Trace(Tick())), sysfs.Group("gpu", sysfs.Trace(Tick()))
    jetson.gpu(str(tmp_path / "a"), ga)
    jetson.gpu(str(tmp_path / "b"), gb)
    assert ga.sensors["usage"]["id"] != gb.sensors["usage"]["id"]
    assert ga.sensors["usage"]["id"] != ga.sensors["freq"]["id"]
    # gpu.0 linked to the devfreq device: the same file, so the same source
    (tmp_path / "a/devices/platform").mkdir(parents=True)
    (tmp_path / "a/devices/platform/gpu.0").symlink_to(tmp_path / "a/class/devfreq/17000000.gpu/device")
    assert sysfs.canonical(str(tmp_path / "a/devices/platform/gpu.0/load"), str(tmp_path / "a")) == \
        sysfs.canonical(str(tmp_path / "a/class/devfreq/17000000.gpu/device/load"), str(tmp_path / "a"))


# ---------- read spans ----------

class Script:
    """Elapsed clock with scripted values per read, in calling order."""

    def __init__(self, *values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


def test_label_read_later_does_not_refresh_the_number(tmp_path):
    chip(tmp_path, "devices/platform/i2c/1-0040", 3, {"name": "c", "temp1_input": 0, "temp1_label": "Zero"})
    tick = Tick()
    (temps, _, _), g = hwmon(tmp_path, tick)
    span = g["temperature"].sensors["c Zero"]["span"]
    assert temps == {"c Zero": 0.0} and span is not None  # a measured 0 has its read too
    assert span[1] < tick.ns - 1000  # the label was read after it; its read is not this span


def test_computed_and_fan_spans(tmp_path):
    chip(tmp_path, "devices/platform/i2c/1-0040", 3, CHIP)
    _, g = hwmon(tmp_path)
    vdd = g["power"].sensors["VDD"]["span"]
    vin = g["power"].sensors["VIN"]["span"]
    assert vdd[1] - vdd[0] > vin[1] - vin[0]  # from the current read's start to the voltage read's end
    rpm, pwm = (v["span"] for v in g["fans"].sensors.values())
    assert rpm[1] < pwm[0]  # two reads, two spans


def test_gpu_spans_skip_the_failed_candidate(tmp_path):
    for path, value in {"class/devfreq/17000000.gpu/device/load": "bad", "devices/platform/gpu.0/load": 500,
                        "class/devfreq/17000000.gpu/cur_freq": 1, "class/devfreq/17000000.gpu/max_freq": 2}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(str(value))
    tick = Tick()
    g = sysfs.Group("gpu", sysfs.Trace(tick))
    jetson.gpu(str(tmp_path), g)
    usage, freq, max_freq = (g.sensors[k]["span"] for k in ("usage", "freq", "max_freq"))
    assert usage[0] > 10**12 + 1000  # the failed candidate's read started at +1000 ns; this one after it
    assert usage[1] < freq[0] < freq[1] < max_freq[0]


def test_opens_are_the_same_with_records(tmp_path, monkeypatch):
    """Recording adds no reads: the same files are opened with and without a trace."""
    chip(tmp_path, "devices/platform/i2c/1-0040", 3, CHIP)
    opened, real = [], open
    monkeypatch.setattr(sysfs, "open", lambda p, *a, **k: opened.append(p) or real(p, *a, **k), raising=False)
    common.hwmon_sensors(root=str(tmp_path / "class" / "hwmon"))
    plain, opened[:] = list(opened), []
    hwmon(tmp_path)
    assert opened == plain


# ---------- the recorded collection ----------

def resolve(doc, ptr):
    for part in ptr.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """collector.collect_recorded() on a fake tree: CPUs 0, 2 and 5, a labelled chip and a thermal zone."""
    d = chip(tmp_path, "devices/platform/i2c/1-0040", 3, dict(CHIP, temp1_label="a/b~c 보드 온도"))
    chip(tmp_path, "devices/platform/i2c/1-0041", 4, {"name": "fan2", "fan1_input": 0})
    zone(tmp_path, 0, "cpu-thermal", 50000)
    monkeypatch.setattr(collector, "BOARD", None)
    monkeypatch.setattr(common, "hwmon_sensors", functools.partial(common.hwmon_sensors, root=str(tmp_path / "class/hwmon")))
    monkeypatch.setattr(common, "thermal_zones", functools.partial(common.thermal_zones, root=str(tmp_path / "class/thermal")))
    real = open

    def fake(path, *a, **k):
        if str(path).startswith("/sys/devices/system/cpu/"):
            if "cpu2/" in path:
                raise OSError(5, "EIO")
            return io.StringIO("1200000\n")
        return real(path, *a, **k)
    monkeypatch.setattr(sysfs, "open", fake, raising=False)
    tick = Tick()
    p = Proc(monkeypatch)
    cpu = CpuCounters(tick)
    p.readings += [{n: idle_busy(0, 0) for n in (0, 2, 5)}, {n: idle_busy(10, 10) for n in (0, 2, 5)}]
    collector.collect_recorded(cpu, None, tick)  # warmup
    return collector.collect_recorded(cpu, None, tick), tick, p, d


def test_pointers_resolve_in_the_output(recorded):
    result, tick, p, _ = recorded
    stats = result.stats
    assert [c["id"] for c in stats["cpu"]] == [0, 2, 5]
    for ptr, info in result.sensors.items():
        value = resolve(stats, ptr)  # every pointer exists in this snapshot
        assert (info["span"] is None) == (value is None), ptr  # a null has no read, a value has one
    assert set(result.sensors) >= {"/temperature/ina a~1b~0c 보드 온도", "/temperature/cpu", "/power/VIN", "/power/VDD",
                                   "/fans/0/rpm", "/fans/0/percent", "/fans/1/rpm", "/cpu/1/freq"}
    assert resolve(stats, "/cpu/1/freq") is None  # CPU 2 is the list's second row; its clock failed
    assert resolve(stats, "/fans/1/rpm") == 0 and result.sensors["/fans/1/rpm"]["span"]
    assert "/fans/1/percent" in result.sensors and resolve(stats, "/fans/1/percent") is None  # no pwm: null, no read
    for ptr in result.targets:  # every value that needs a record has one with a read
        if resolve(stats, ptr) is not None:
            assert result.sensors[ptr]["span"], ptr
    assert p.reads == 2  # one /proc/stat reading per collection, as before


def test_required_reads_are_named_and_timed(recorded):
    result, tick, *_ = recorded
    assert set(result.required) == {"cpu", "memory", "disk", "uptime"} and all(result.required.values())
    assert result.clock is tick


def test_label_fallback_pointer(recorded):
    result, tick, p, d = recorded
    (d / "temp1_label").write_bytes(b"\xff\n")  # C1: unreadable label, the channel name is used
    p.readings.append({n: idle_busy(20, 20) for n in (0, 2, 5)})
    again = collector.collect_recorded(CpuCounters(tick), None, tick)
    assert "/temperature/ina temp1" in again.sensors and resolve(again.stats, "/temperature/ina temp1") == 40.0
    assert again.sensors["/temperature/ina temp1"]["id"] == result.sensors["/temperature/ina a~1b~0c 보드 온도"]["id"]


def test_direct_collect_has_no_records():
    s = collector.collect()
    assert "sensor_meta" not in s and not isinstance(s, Collected)


# ---------- data age in the Sampler ----------

MS = 10**6
BASE = {"id": "src1:x", "provider": "hwmon", "identity_basis": "device_channel", "unit": "celsius"}


def collected(c, required, sensors=(), values=None, clock=None, targets=None, extra=None):
    """A Collected whose spans are ms offsets from the collection start (which takes 300 ms). sensors:
    {name: span} for /temperature/<name> with value 1.0 in the stats; values: more temperatures without a
    record; extra: records whose pointers are not in the stats. Targets are all temperatures unless given."""
    def collect():
        start = c.ns
        at = lambda s: None if s is None else (start + s[0] * MS, start + s[1] * MS)  # noqa: E731
        c.advance(0.3)
        temps = {**{n: 1.0 for n in dict(sensors)}, **(values or {})}
        meta = {f"/temperature/{n}": {**BASE, "span": at(s)} for n, s in dict(sensors).items()}
        meta.update({p: {**BASE, "span": at(s)} for p, s in (extra or {}).items()})
        req = {f"r{i}": at(s) for i, s in enumerate(required)}
        tg = targets if targets is not None else [f"/temperature/{n}" for n in temps]
        return Collected({"temperature": temps}, meta, req, tg, clock)
    return collect


def recorded_sampler(c, required, **kw):
    clock = lambda: c.ns  # noqa: E731 - the one clock both use
    s = Sampler(None, clock=(clock, {"source": "fake"}), wall=lambda: c.wall)
    s.collect = collected(c, required, clock=clock, **kw)
    return s


def test_data_age_numbers():
    """Collection 0-300 ms, current reads from 100 ms, answer at 500 ms."""
    c = Clock()
    s = recorded_sampler(c, [(100, 110), (290, 300)], sensors={"x": (150, 160)})
    s._attempt()
    c.advance(0.2)
    stats, status = s.read()
    sample = stats["sample"]
    assert (sample["duration_ms"], sample["age_ms"], sample["cycle_age_ms"], sample["data_age_ms"]) == (300, 200, 500, 400)
    assert sample["data_age_basis"] == "oldest_current_read_start"
    assert stats["sensor_meta"] == {"/temperature/x": {**BASE, "read": {"started_offset_ms": 150.0, "completed_offset_ms": 160.0}}}
    assert status["sample"]["data_age_basis"] == "oldest_current_read_start" and status["sample"]["cycle_age_ms"] == 500
    # the same timings from a plain dict callable: from the collection start
    c2 = Clock()

    def plain():
        c2.advance(0.3)
        return {"v": 1}
    p = fake(plain, c2)
    p._attempt()
    c2.advance(0.2)
    sample = p.read()[0]["sample"]
    assert (sample["data_age_ms"], sample["data_age_basis"]) == (500, "cycle_start_upper_bound")


def test_a_sensor_read_before_the_required_ones_counts():
    """Sensor T read at 20-21 ms, required reads from 100 ms, answer at 500 ms: 480 ms, from T's read."""
    c = Clock()
    s = recorded_sampler(c, [(100, 110), (250, 260)], sensors={"T": (20, 21)})
    s._attempt()
    c.advance(0.2)
    stats = s.read()[0]
    assert stats["sample"]["data_age_ms"] == 480.0 and stats["sample"]["data_age_basis"] == "oldest_current_read_start"
    assert stats["sensor_meta"]["/temperature/T"]["read"]["started_offset_ms"] == 20.0


def test_stale_boundary_on_read_basis():
    c = Clock()
    s = recorded_sampler(c, [(100, 110)])
    s._attempt()
    c.advance(4.8)  # collection took 0.3 s, the read started at 0.1 s: now exactly stale_after ago
    assert s.read()[0]["sample"]["data_age_ms"] == 5000.0
    c.ns += 1
    stats, status = s.read()
    assert stats is None and status["state"] == "stale" and status["sample"]["data_age_basis"] == "oldest_current_read_start"


@pytest.mark.parametrize("kw, problem", [
    ({"sensors": {"x": (100, 110)}, "values": {"y": 2.0}}, "a value without its record"),
    ({"sensors": {"x": (-10, 5)}}, "a value without a valid read"),     # before the collection
    ({"sensors": {"x": (400, 410)}}, "a value without a valid read"),   # after it ended
    ({"sensors": {"x": (160, 150)}}, "a value without a valid read"),   # reversed
    ({"sensors": {"x": (100, 110)}, "extra": {"/temperature/gone": (20, 21)}}, "a record for a value that is not there"),
    ({"sensors": {"x": (100, 110)}, "targets": ["/temperature/x", "/power/VIN"]}, "a value without its record"),
])
def test_records_that_do_not_match_fall_back(kw, problem, capsys):
    c = Clock()
    s = recorded_sampler(c, [(100, 110)], **kw)
    s._attempt()
    stats = s.read()[0]
    sample, meta = stats["sample"], stats.get("sensor_meta", {})
    assert sample["data_age_basis"] == "cycle_start_upper_bound" and sample["data_age_ms"] == sample["cycle_age_ms"]
    assert "/temperature/gone" not in meta  # never a pointer to nothing
    assert stats["temperature"]["x"] == 1.0  # the values are published as collected
    assert problem in capsys.readouterr().err
    s._attempt()
    assert capsys.readouterr().err == ""  # the same problem is logged once


@pytest.mark.parametrize("required", [[None], [(100, 110), None], []])
def test_missing_required_reads_fall_back(required):
    c = Clock()
    s = recorded_sampler(c, required, sensors={"x": (150, 160)})
    s._attempt()
    assert s.read()[0]["sample"]["data_age_basis"] == "cycle_start_upper_bound"


@pytest.mark.parametrize("sensors, targets", [(None, []), ({"/temperature/T": None}, ["/temperature/T"]),
                                              ({5: {}}, []), ({}, None), ("x", "y")])
def test_malformed_records_keep_the_values(sensors, targets):
    """Records of the wrong shape: the snapshot is published with its values, from the cycle start."""
    c = Clock()
    clock = lambda: c.ns  # noqa: E731

    def collect():
        start = c.ns
        c.advance(0.3)
        return Collected({"temperature": {"T": 43.0}}, sensors, {"cpu": (start + MS, start + 2 * MS)}, targets, clock)
    s = Sampler(collect, clock=(clock, {"source": "fake"}), wall=lambda: c.wall)
    s._attempt()  # also the very first attempt
    stats, status = s.read()
    assert stats["temperature"] == {"T": 43.0} and stats["sample"]["sequence"] == 1
    assert stats["sample"]["data_age_basis"] == "cycle_start_upper_bound"
    assert status["last_attempt"]["state"] == "ok" and status["last_attempt"]["consecutive_failures"] == 0


def test_writer_survives_bad_records_and_recovers():
    """The real writer thread: good, malformed, good records; values, sequence and last_attempt follow."""
    import threading
    import time
    c = Clock()
    clock = lambda: c.ns  # noqa: E731
    n = [0]
    published = threading.Event()

    def collect():
        n[0] += 1
        start = c.ns
        c.advance(0.01)
        span = (start + 1000, start + 2000)
        if n[0] == 2:  # malformed records
            return Collected({"temperature": {"T": float(n[0])}}, {"/temperature/T": None}, {"cpu": span}, None, clock)
        if n[0] >= 3:
            published.set()
        return Collected({"temperature": {"T": float(n[0])}}, {"/temperature/T": {**BASE, "span": span}},
                         {"cpu": span}, ["/temperature/T"], clock)
    s = Sampler(collect, interval=0.01, clock=(clock, {"source": "fake"}), wall=lambda: c.wall).start()
    try:
        assert published.wait(5)
        deadline = time.monotonic() + 5
        while s.read()[0]["sample"]["sequence"] < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        stats, status = s.read()
        assert s._thread.is_alive()
        assert stats["temperature"]["T"] == float(stats["sample"]["sequence"]) and stats["sample"]["sequence"] >= 3
        assert stats["sample"]["data_age_basis"] == "oldest_current_read_start"  # good records again
        assert status["last_attempt"]["state"] == "ok"
    finally:
        s.stop()
        s._thread.join(5)


def test_a_slow_log_write_does_not_block_status_or_stop(monkeypatch):
    """The fallback is logged outside the state lock: read() and stop() answer while the write hangs."""
    import threading
    c = Clock()
    clock = lambda: c.ns  # noqa: E731
    entered, gate = threading.Event(), threading.Event()

    class SlowErr:
        def write(self, text):
            entered.set()
            gate.wait(5)
            return len(text)

        def flush(self):
            pass
    s = Sampler(collected(c, [None], clock=clock), clock=(clock, {"source": "fake"}), wall=lambda: c.wall)
    monkeypatch.setattr(sys, "stderr", SlowErr())
    writer = threading.Thread(target=s._attempt)
    writer.start()
    try:
        assert entered.wait(5)
        done = []
        reader = threading.Thread(target=lambda: done.append(s.read()) or s.stop() or done.append("stopped"))
        reader.start()
        reader.join(2)
        assert done[1:] == ["stopped"] and done[0][1]["state"] in ("starting", "stale")
    finally:
        gate.set()
        writer.join(5)
        reader.join(5)
    assert s.read()[0]["sample"]["sequence"] == 1  # published once the log line was written


def test_records_on_another_clock_are_not_used():
    c = Clock()
    s = Sampler(None, clock=(lambda: c.ns, {"source": "fake"}), wall=lambda: c.wall)
    s.collect = collected(c, [(100, 110)], sensors={"x": (100, 110)}, clock=lambda: c.ns)  # another function
    s._attempt()
    stats = s.read()[0]
    assert stats["sample"]["data_age_basis"] == "cycle_start_upper_bound"
    assert stats["sensor_meta"]["/temperature/x"]["read"] is None


def test_too_slow_still_counts_the_whole_collection():
    c = Clock()
    s = recorded_sampler(c, [(100, 110)])
    inner = s.collect

    def slow():
        result = inner()
        c.advance(5.8)
        return result
    s.collect = slow
    s._attempt()
    assert s.read()[1]["last_attempt"]["reason"] == "collection_too_slow"  # recent reads; still dropped


def test_published_records_stay_and_plain_dicts_cannot_fake_them():
    c = Clock()
    s = recorded_sampler(c, [(100, 110)], sensors={"x": (100, 110)})
    s._attempt()
    first = s.read()[0]
    first["sensor_meta"]["/temperature/x"]["read"] = None  # changing a returned copy
    c.advance(0.5)
    again = s.read()[0]
    assert again["sensor_meta"]["/temperature/x"]["read"] == {"started_offset_ms": 100.0, "completed_offset_ms": 110.0}
    assert again["sample"]["sequence"] == 1
    assert s.latest() == {"temperature": {"x": 1.0}}  # no Sampler metadata
    s.collect = lambda: (_ for _ in ()).throw(OSError("memory"))  # a failed collection: last good kept as it was
    s._attempt()
    assert s.read()[0]["sensor_meta"] == again["sensor_meta"]
    p = fake(lambda: {"v": 2, "sensor_meta": {"/v": {"read": {"started_offset_ms": 0}}}}, Clock())
    p._attempt()
    stats = p.read()[0]
    assert "sensor_meta" not in stats and stats["sample"]["data_age_basis"] == "cycle_start_upper_bound"


@pytest.mark.parametrize("step", [-3600, 3600])
def test_wall_clock_steps_do_not_move_read_offsets(step):
    c = Clock()
    s = recorded_sampler(c, [(100, 110)], sensors={"x": (100, 110)})
    s._attempt()
    c.advance(0.2, wall=step)
    stats = s.read()[0]
    assert stats["sample"]["data_age_ms"] == 400.0
    assert stats["sensor_meta"]["/temperature/x"]["read"] == {"started_offset_ms": 100.0, "completed_offset_ms": 110.0}


def test_service_end_to_end_reports_no_paths(recorded):
    """The service's own path: collect_recorded through the Sampler; no paths or raw ns in the API."""
    result, tick, p, _ = recorded
    c = Clock()
    s = Sampler(None, clock=(tick, {"source": "fake"}), wall=lambda: c.wall)
    cpu = CpuCounters(tick)
    p.readings += [{n: idle_busy(30, 30) for n in (0, 2, 5)}, {n: idle_busy(40, 40) for n in (0, 2, 5)}]
    s.collect = functools.partial(collector.collect_recorded, cpu, None, tick)
    s._attempt()
    s._attempt()
    stats = s.read()[0]
    assert stats["sample"]["data_age_basis"] == "oldest_current_read_start"
    assert stats["sample"]["data_age_ms"] <= stats["sample"]["cycle_age_ms"]
    text = json.dumps(stats["sensor_meta"])
    assert "/sys" not in text and "tmp" not in text and str(10**12)[:6] not in text
    for ptr in stats["sensor_meta"]:
        resolve(stats, ptr)


@pytest.mark.parametrize("device, basis", [
    ("devices/virtual", "resolved_path"),                                   # devices/virtual/hwmon/hwmonN
    ("devices/virtual/thermal/thermal_zone0", "resolved_path"),
    ("devices/virtual/platform/fan_controller", "resolved_path"),
    ("devices/platform/i2c/1-0040", "device_channel"),
    ("devices/platform/virtual_fan", "device_channel"),                     # a real device named "virtual..."
])
def test_virtual_devices_are_path_based(tmp_path, device, basis):
    chip(tmp_path, device, 3, {"name": "x", "temp1_input": 40000})
    _, g = hwmon(tmp_path)
    assert g["temperature"].sensors["x temp1"]["identity_basis"] == basis
