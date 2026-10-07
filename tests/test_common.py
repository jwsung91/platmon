import pytest

from collector import detect, jetson
from collector import common
from collector.common import CpuCounters, cpu_percent, cpu_times, hwmon_sensors, os_release, thermal_zones


@pytest.mark.parametrize("before, after, expected", [
    # user nice system idle iowait irq softirq steal
    ({0: [100, 0, 100, 700, 100, 0, 0, 0]}, {0: [150, 0, 150, 800, 100, 0, 0, 0]}, ({0: 50.0}, {})),
    ({0: [0] * 8}, {0: [0, 0, 0, 90, 10, 0, 0, 0]}, ({0: 0.0}, {})),  # measured idle (iowait counts as idle)
    ({0: [0] * 8}, {0: [40, 10, 20, 0, 0, 10, 10, 10]}, ({0: 100.0}, {})),
    ({0: [0] * 8}, {0: [1, 0, 0, 2, 0, 0, 0, 0]}, ({0: 33.3}, {})),  # one decimal, rounded once at the end
    # no ticks elapsed: nothing was measured, which is not 0 % (this used to read 0.0)
    ({0: [1, 1, 1, 1, 1]}, {0: [1, 1, 1, 1, 1]}, ({}, {0: "no_ticks"})),
    # cpu1 offline, cpu3 went offline between samples: ids kept, nothing mispaired
    ({0: [0, 0, 0, 0, 0], 2: [0, 0, 0, 0, 0], 3: [0, 0, 0, 0, 0]},
     {0: [10, 0, 0, 10, 0], 2: [0, 0, 0, 10, 0]}, ({0: 50.0, 2: 0.0}, {})),
    # VM host: guest (and guest_nice) time is already included in user (and nice); not counted twice
    #  user nice system idle iowait irq softirq steal guest guest_nice
    ({0: [0] * 10}, {0: [50, 0, 0, 50, 0, 0, 0, 0, 50, 0]}, ({0: 50.0}, {})),
    ({0: [0] * 10}, {0: [0, 50, 0, 50, 0, 0, 0, 0, 0, 50]}, ({0: 50.0}, {})),
    # a core with no earlier reading (new or back online) and one whose iowait went down: no usage for
    # either, and the other core is still measured; nothing negative, nothing over 100 %
    ({0: [0] * 8, 1: [0, 0, 0, 0, 50, 0, 0, 0]},
     {0: [10] + [0] * 7, 1: [0, 0, 0, 100, 40, 0, 0, 0], 2: [5] * 8},
     ({0: 100.0}, {1: "counter_regressed", 2: "warmup"})),
])
def test_cpu_percent(before, after, expected):
    assert cpu_percent(before, after) == expected


class Proc:
    """Fake /proc/stat readings (served in order) and a fake elapsed clock, for CpuCounters."""

    def __init__(self, monkeypatch):
        self.ns, self.readings, self.reads = 10**12, [], 0
        monkeypatch.setattr(common, "cpu_times", self.read)

    def read(self):
        self.reads += 1
        reading = self.readings.pop(0)
        if isinstance(reading, Exception):
            raise reading
        return reading

    def counters(self, max_gap=5.0):
        return CpuCounters(lambda: self.ns, max_gap=max_gap)

    def sample(self, counters, after_s, reading):
        self.ns += round(after_s * 1e9)
        self.readings.append(reading)
        return counters.sample()


def idle_busy(idle, busy):
    return [busy, 0, 0, idle, 0, 0, 0, 0]


def test_first_reading_warms_up_then_measures(monkeypatch):
    p = Proc(monkeypatch)
    c = p.counters()
    assert p.sample(c, 0, {0: idle_busy(0, 0), 1: idle_busy(0, 0)}) == (
        {}, {"mode": "interval", "window_ms": None,
             "unavailable": [{"id": 0, "reason": "warmup"}, {"id": 1, "reason": "warmup"}]})
    # interval 1 s configured, readings 1.25 s apart: the window is what was measured; usage is a tick ratio
    usage, sampling = p.sample(c, 1.25, {0: idle_busy(100, 100), 1: idle_busy(200, 0)})
    assert usage == {0: 50.0, 1: 0.0}
    assert sampling == {"mode": "interval", "window_ms": 1250.0, "unavailable": []}
    assert p.sample(c, 3, {0: idle_busy(200, 200), 1: idle_busy(400, 0)})[0] == usage  # same ticks, longer window


def test_cores_come_and_go(monkeypatch):
    p = Proc(monkeypatch)
    c = p.counters()
    p.sample(c, 0, {0: idle_busy(0, 0), 1: idle_busy(0, 0)})
    usage, sampling = p.sample(c, 1, {0: idle_busy(10, 10), 1: idle_busy(20, 0), 2: idle_busy(5, 5)})
    assert usage == {0: 50.0, 1: 0.0} and sampling["unavailable"] == [{"id": 2, "reason": "warmup"}]
    usage, sampling = p.sample(c, 1, {0: idle_busy(20, 20), 2: idle_busy(10, 10)})  # cpu1 went offline
    assert usage == {0: 50.0, 2: 50.0} and sampling["unavailable"] == []  # gone: neither shown nor listed
    usage, sampling = p.sample(c, 1, {0: idle_busy(30, 30), 1: idle_busy(500, 500), 2: idle_busy(20, 10)})
    assert usage == {0: 50.0, 2: 0.0}
    assert sampling["unavailable"] == [{"id": 1, "reason": "warmup"}]  # back: a fresh baseline, not the old one
    assert p.sample(c, 1, {0: idle_busy(40, 40), 1: idle_busy(510, 510), 2: idle_busy(30, 10)})[0][1] == 50.0


def test_counter_regression_is_dropped_and_rebased(monkeypatch):
    p = Proc(monkeypatch)
    c = p.counters()
    p.sample(c, 0, {0: idle_busy(100, 100), 1: idle_busy(100, 100)})
    usage, sampling = p.sample(c, 1, {0: idle_busy(50, 150), 1: idle_busy(110, 110)})
    assert usage == {1: 50.0} and sampling["unavailable"] == [{"id": 0, "reason": "counter_regressed"}]
    assert p.sample(c, 1, {0: idle_busy(60, 160), 1: idle_busy(120, 120)})[0] == {0: 50.0, 1: 50.0}


def test_no_ticks_is_not_zero(monkeypatch):
    p = Proc(monkeypatch)
    c = p.counters()
    p.sample(c, 0, {0: idle_busy(10, 10)})
    usage, sampling = p.sample(c, 1, {0: idle_busy(10, 10)})
    assert usage == {} and sampling["unavailable"] == [{"id": 0, "reason": "no_ticks"}]


@pytest.mark.parametrize("step", [0, -1])
def test_invalid_interval(monkeypatch, step):
    p = Proc(monkeypatch)
    c = p.counters()
    p.sample(c, 0, {0: idle_busy(0, 0)})
    usage, sampling = p.sample(c, step, {0: idle_busy(10, 10)})
    assert usage == {} and sampling == {"mode": "interval", "window_ms": None,
                                        "unavailable": [{"id": 0, "reason": "invalid_interval"}]}
    assert p.sample(c, 1, {0: idle_busy(20, 20)})[0] == {0: 50.0}  # rebased on the reading it could not use


def test_gap_boundary_and_recovery(monkeypatch):
    p = Proc(monkeypatch)
    c = p.counters(max_gap=5.0)
    p.sample(c, 0, {0: idle_busy(0, 0)})
    assert p.sample(c, 5, {0: idle_busy(10, 10)})[0] == {0: 50.0}  # exactly max_gap: still averaged
    p.ns += 1
    usage, sampling = p.sample(c, 5, {0: idle_busy(20, 20)})
    assert usage == {} and sampling == {"mode": "interval", "window_ms": 5000.0,
                                        "unavailable": [{"id": 0, "reason": "gap"}]}
    usage, sampling = p.sample(c, 1, {0: idle_busy(30, 20)})
    assert usage == {0: 0.0} and sampling["window_ms"] == 1000.0


def test_read_failure_raises_and_restarts_warmup(monkeypatch):
    p = Proc(monkeypatch)
    c = p.counters()
    p.sample(c, 0, {0: idle_busy(0, 0)})
    with pytest.raises(OSError):
        p.sample(c, 1, OSError("unreadable"))
    usage, sampling = p.sample(c, 1, {0: idle_busy(10, 10)})
    assert usage == {} and sampling["unavailable"] == [{"id": 0, "reason": "warmup"}]


@pytest.mark.parametrize("text", [
    "cpu  1 2 3 4 5 6 7 8\nintr 0\n",            # the total line only: not "0 CPUs"
    "cpu0 1 2 3 4 5 6 7 8\ncpu2 1 x 3 4 5 6 7 8\n",  # a counter that is not a number
    "cpu0\n",                                      # no counters
    "cpu0 1 0 0 1\n",                              # fewer than user..steal
    "cpu0 1 2 3 4 5 6 7 8\ncpu1 1 2 3 4 5 6 7",    # last line short, no trailing newline
])
def test_cpu_times_rejects_broken_readings(tmp_path, text):
    stat = tmp_path / "stat"
    stat.write_text(text)
    with pytest.raises(ValueError):
        cpu_times(str(stat))


def test_cpu_times_reads_eight_or_more_counters(tmp_path):
    stat = tmp_path / "stat"
    stat.write_text("cpu  9 9 9 9 9 9 9 9 9 9\ncpu0 1 2 3 4 5 6 7 8\ncpu1 1 2 3 4 5 6 7 8 9 10\nctxt 5\n")
    assert cpu_times(str(stat)) == {0: [1, 2, 3, 4, 5, 6, 7, 8], 1: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}


def test_cpu_percent_does_not_cut_readings_short():
    with pytest.raises(ValueError):
        cpu_percent({0: [0] * 8}, {0: [1, 0, 0, 1, 0]})


def stat_files(tmp_path, monkeypatch, lines):
    """The real /proc/stat parser on a sequence of files, one per reading."""
    paths = []
    for i, line in enumerate(lines):
        paths.append(tmp_path / f"stat{i}")
        paths[-1].write_text("cpu  0 0 0 0 0 0 0 0\n" + line + "\n")
    real = common.cpu_times
    monkeypatch.setattr(common, "cpu_times", lambda: real(str(paths.pop(0))))


GOOD = ["cpu0 0 0 0 0 0 0 0 0", "cpu0 2 0 0 2 0 0 0 0", "cpu0 3 0 0 3 0 0 0 0"]


@pytest.mark.parametrize("first_ok", [True, False])
def test_broken_reading_is_not_a_baseline(tmp_path, monkeypatch, first_ok):
    """A short line fails that reading and clears the baseline; the next valid one warms up, then measures."""
    stat_files(tmp_path, monkeypatch, (GOOD[:1] if first_ok else []) + ["cpu0 1 0 0 1"] + GOOD[1:])
    now = [0]
    c = CpuCounters(lambda: now[0], max_gap=5.0)

    def sample():
        now[0] += 10**9
        return c.sample()

    if first_ok:
        assert sample()[1]["unavailable"] == [{"id": 0, "reason": "warmup"}]
    with pytest.raises(ValueError):
        sample()
    assert sample() == ({}, {"mode": "interval", "window_ms": None, "unavailable": [{"id": 0, "reason": "warmup"}]})
    assert sample() == ({0: 50.0}, {"mode": "interval", "window_ms": 1000.0, "unavailable": []})


def test_counters_are_independent(monkeypatch):
    p = Proc(monkeypatch)
    a, b = p.counters(), p.counters()
    p.sample(a, 0, {0: idle_busy(0, 0)})
    p.sample(a, 1, {0: idle_busy(10, 10)})
    assert p.sample(b, 0, {0: idle_busy(20, 20)})[1]["unavailable"] == [{"id": 0, "reason": "warmup"}]
    # a compares with its own last reading (10, 10): 33.3 %; against b's (20, 20) it would read 0 %
    assert p.sample(a, 1, {0: idle_busy(30, 20)})[0] == {0: 33.3}


@pytest.mark.parametrize("compatible, has_dmi, expected", [
    ("nvidia,p3767-0005\0nvidia,tegra234", False, ("Jetson Orin", jetson)),
    ("raspberrypi,5-model-b\0brcm,bcm2712", False, ("Raspberry Pi", None)),
    ("", True, ("PC", None)),
    ("rockchip,rk3588", False, ("Linux", None)),
])
def test_detect(compatible, has_dmi, expected):
    assert detect(compatible, has_dmi) == expected


def fake_hwmon(root, chips):
    for i, files in enumerate(chips):
        d = root / f"hwmon{i}"
        d.mkdir()
        for name, value in files.items():
            (d / name).write_text(str(value))
    return str(root)


def test_hwmon_rails_and_pwm_only_fan(tmp_path):
    """ina3221 rails, unlabeled sum channel ignored, pwm-fan without tach, non-standard rpm left to boards."""
    temps, power, fans = hwmon_sensors(root=fake_hwmon(tmp_path, [
        {"name": "pwmfan", "pwm1": 76},
        {"name": "ina3221", "in1_label": "VDD_IN", "in1_input": 5000, "curr1_input": 1200,
         "in4_input": 6400, "curr4_input": 2416},
        {"name": "pwm_tach", "rpm": 1636},
    ]))
    assert temps == {}
    assert power == {"VDD_IN": 6.0}
    assert fans == [{"name": "pwmfan", "rpm": None, "percent": 30}]


def test_hwmon_pc(tmp_path):
    """acpitz skipped (already a thermal zone), duplicate nvme labels kept apart, fan with pwm."""
    temps, power, fans = hwmon_sensors(skip={"acpitz"}, root=fake_hwmon(tmp_path, [
        {"name": "acpitz", "temp1_input": 27800},
        {"name": "coretemp", "temp1_label": "Package id 0", "temp1_input": 45000},
        {"name": "nvme", "temp1_label": "Composite", "temp1_input": 38850},
        {"name": "nvme", "temp1_label": "Composite", "temp1_input": 41850},
        {"name": "nct6775", "fan2_input": 950, "pwm2": 128, "power1_input": 12500000},
    ]))
    assert temps == {"coretemp Package id 0": 45.0, "nvme Composite": 38.85,
                     "nvme Composite (hwmon3)": 41.85}
    assert power == {"nct6775 power1": 12.5}
    assert fans == [{"name": "nct6775 fan2", "rpm": 950, "percent": 50}]


def test_thermal_zones(tmp_path):
    """Zone types reported as hwmon names ("-" -> "_"), duplicate zone types kept apart."""
    for i, (zt, t) in enumerate([("cpu-thermal", 51200), ("acpitz", 27800), ("acpitz", 30000)]):
        z = tmp_path / f"thermal_zone{i}"
        z.mkdir()
        (z / "type").write_text(zt)
        (z / "temp").write_text(str(t))
    temps, zone_types = thermal_zones(root=str(tmp_path))
    assert temps == {"cpu": 51.2, "acpitz": 27.8, "acpitz (thermal_zone2)": 30.0}
    assert zone_types == {"cpu_thermal", "acpitz"}


def test_host_paths_from_env(tmp_path):
    """Containers point PLATMON_DEVICE_TREE / PLATMON_HOST_ROOT at bind mounts of the host's paths:
    board detection, disk usage, OS name and (Jetson) L4T release all come from the host, not the image."""
    import json
    import os
    import subprocess
    import sys

    dt = tmp_path / "dt"
    dt.mkdir()
    (dt / "compatible").write_bytes(b"nvidia,p3767-0005\0nvidia,tegra234\0")
    (dt / "model").write_bytes(b"Test Board\0")
    root = tmp_path / "host"
    (root / "etc").mkdir(parents=True)
    (root / "usr/lib").mkdir(parents=True)
    (root / "usr/lib/os-release").write_text('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 22.04.5 LTS"\n')
    (root / "etc/os-release").symlink_to("../usr/lib/os-release")  # relative, as on Ubuntu/Debian
    (root / "etc/nv_tegra_release").write_text("# R36 (release), REVISION: 5.2, GCID: 1, BOARD: generic\n")
    code = ("import collector, json, shutil; s = collector.collect(); "
            "print(json.dumps([collector.PLATFORM, s['model'], s['disk']['total'], shutil.disk_usage(%r).total, "
            "s['system']['os'], s['system'].get('l4t')]))" % str(root))
    env = dict(os.environ, PLATMON_DEVICE_TREE=str(dt), PLATMON_HOST_ROOT=str(root))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    platform, model, disk_total, expected_total, os_name, l4t = json.loads(out.stdout)
    assert (platform, model) == ("Jetson Orin", "Test Board")
    assert disk_total == expected_total
    assert (os_name, l4t) == ("Ubuntu 22.04.5 LTS", "R36.5.2")


@pytest.mark.parametrize("text, expected", [
    ('NAME="Ubuntu"\nVERSION="22.04.5 LTS (Jammy Jellyfish)"\nPRETTY_NAME="Ubuntu 22.04.5 LTS"\n', "Ubuntu 22.04.5 LTS"),
    ("NAME='Raspbian GNU/Linux'\nVERSION='12 (bookworm)'\n", "Raspbian GNU/Linux 12 (bookworm)"),  # no PRETTY_NAME
    ("# comment only\n", None),
    (None, None),  # file missing
])
def test_os_release(text, expected):
    assert os_release(text) == expected


def test_hwmon_same_names_kept_apart(tmp_path):
    """Two chips reporting the same power sensor or rail name: both values stay (first keeps the plain name)."""
    temps, power, fans = hwmon_sensors(root=fake_hwmon(tmp_path, [
        {"name": "ina219", "power1_input": 1000000},
        {"name": "ina219", "power1_input": 2000000},
        {"name": "ina3221", "in1_label": "VDD_IN", "in1_input": 5000, "curr1_input": 1000},
        {"name": "ina3221", "in1_label": "VDD_IN", "in1_input": 5000, "curr1_input": 2000},
    ]))
    assert power == {"ina219 power1": 1.0, "ina219 power1 (hwmon1)": 2.0,
                     "VDD_IN": 5.0, "VDD_IN (hwmon3)": 10.0}


def test_hwmon_unreadable_fan_is_none_not_zero(tmp_path):
    """A fan whose speed cannot be read is unknown (None), not stopped (0)."""
    root = fake_hwmon(tmp_path, [{"name": "nct6775", "fan1_label": "CPU fan"}])
    (tmp_path / "hwmon0" / "fan1_input").mkdir()  # exists, but reading it fails
    assert hwmon_sensors(root=root)[2] == [{"name": "CPU fan", "rpm": None, "percent": None}]


def test_service_path_reads_once_and_does_not_wait(monkeypatch):
    import collector
    reads, real = [], common.cpu_times
    monkeypatch.setattr(common, "cpu_times", lambda: reads.append(1) or real())

    def no_sleep(seconds):
        raise AssertionError(f"slept {seconds} s in the service path")
    monkeypatch.setattr(common.time, "sleep", no_sleep)
    c = CpuCounters()
    first, second = collector.collect(c), collector.collect(c)
    assert len(reads) == 2  # one /proc/stat reading per collection
    assert first["cpu"] == [] and {u["reason"] for u in first["cpu_sampling"]["unavailable"]} == {"warmup"}
    assert second["cpu_sampling"]["mode"] == "interval" and second["cpu_sampling"]["window_ms"] > 0


def test_oneshot_does_not_touch_the_service_baseline(monkeypatch):
    p = Proc(monkeypatch)
    monkeypatch.setattr(common.time, "sleep", lambda seconds: None)
    c = p.counters()
    p.sample(c, 0, {0: idle_busy(0, 0)})
    p.readings += [{0: idle_busy(1000, 0)}, {0: idle_busy(1000, 1000)}]  # the one-off call's own two readings
    s = common.collect()
    assert s["cpu"][0]["usage"] == 100.0 and s["cpu_sampling"]["mode"] == "oneshot"
    assert p.sample(c, 1, {0: idle_busy(10, 10)})[0] == {0: 50.0}  # still its own baseline, not the one-shot's


def check_oneshot(s):
    """What a one-off reading must look like on any host: every CPU read is either measured or listed with
    a one-shot reason, once; there may be none measured (e.g. a single CPU whose iowait went down)."""
    sampling = s["cpu_sampling"]
    assert sampling["mode"] == "oneshot"
    measured = [c["id"] for c in s["cpu"]]
    missing = [u["id"] for u in sampling["unavailable"]]
    assert measured or missing
    assert len(set(measured + missing)) == len(measured) + len(missing)  # each CPU in one list
    assert all(0 <= c["usage"] <= 100 for c in s["cpu"])
    assert {u["reason"] for u in sampling["unavailable"]} <= {"warmup", "counter_regressed", "no_ticks"}


def test_direct_collect_is_a_oneshot_reading():
    """collect() without counters, on this host: two real readings 250 ms apart, nothing kept. Which CPUs
    have a usage depends on the host (exact values and reasons are tested with fixtures)."""
    import collector
    s = collector.collect()
    assert s["cpu_sampling"]["window_ms"] >= 250
    check_oneshot(s)


def test_oneshot_single_cpu_iowait_drop(monkeypatch):
    """A one-CPU host whose iowait went down between the two readings: no usage at all, not a made-up 0 %."""
    p = Proc(monkeypatch)
    monkeypatch.setattr(common.time, "sleep", lambda seconds: None)
    p.readings += [{0: [10, 0, 0, 100, 50, 0, 0, 0]}, {0: [20, 0, 0, 110, 40, 0, 0, 0]}]
    s = common.collect()
    assert s["cpu"] == [] and s["cpu_sampling"]["unavailable"] == [{"id": 0, "reason": "counter_regressed"}]
    check_oneshot(s)


def test_oneshot_reports_unusable_cpus(monkeypatch):
    """The one-off path uses the same rules: a CPU that appears between its two readings warms up, one whose
    iowait went down is counter_regressed, and the others are still measured."""
    p = Proc(monkeypatch)
    monkeypatch.setattr(common.time, "sleep", lambda seconds: None)
    p.readings += [{0: idle_busy(0, 0), 1: [0, 0, 0, 0, 50, 0, 0, 0]},
                   {0: idle_busy(10, 10), 1: [0, 0, 0, 100, 40, 0, 0, 0], 2: idle_busy(5, 5)}]
    s = common.collect()
    assert [(c["id"], c["usage"]) for c in s["cpu"]] == [(0, 50.0)]
    assert s["cpu_sampling"]["mode"] == "oneshot" and s["cpu_sampling"]["unavailable"] == [
        {"id": 1, "reason": "counter_regressed"}, {"id": 2, "reason": "warmup"}]
    check_oneshot(s)
