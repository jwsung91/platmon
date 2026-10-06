import pytest

from server import cpu_percent, detect_platform, hwmon_sensors, power_mode_name, thermal_zones


@pytest.mark.parametrize("before, after, expected", [
    # user nice system idle iowait irq softirq steal
    ({0: [100, 0, 100, 700, 100, 0, 0, 0]}, {0: [150, 0, 150, 800, 100, 0, 0, 0]}, {0: 50.0}),
    ({0: [1, 1, 1, 1, 1]}, {0: [1, 1, 1, 1, 1]}, {0: 0.0}),  # no ticks elapsed
    # cpu1 offline, cpu3 went offline between samples: ids kept, nothing mispaired
    ({0: [0, 0, 0, 0, 0], 2: [0, 0, 0, 0, 0], 3: [0, 0, 0, 0, 0]},
     {0: [10, 0, 0, 10, 0], 2: [0, 0, 0, 10, 0]}, {0: 50.0, 2: 0.0}),
])
def test_cpu_percent(before, after, expected):
    assert cpu_percent(before, after) == expected


@pytest.mark.parametrize("mode_id, expected", [("2", "MAXN_SUPER"), ("9", "9")])
def test_power_mode_name(mode_id, expected):
    conf = "< POWER_MODEL ID=0 NAME=15W >\n< POWER_MODEL ID=2 NAME=MAXN_SUPER >"
    assert power_mode_name(mode_id, conf) == expected


@pytest.mark.parametrize("compatible, has_dmi, expected", [
    ("nvidia,p3767-0005\0nvidia,tegra234", False, "Jetson Orin"),
    ("raspberrypi,5-model-b\0brcm,bcm2712", False, "Raspberry Pi"),
    ("", True, "PC"),
    ("rockchip,rk3588", False, "Linux"),
])
def test_detect_platform(compatible, has_dmi, expected):
    assert detect_platform(compatible, has_dmi) == expected


def fake_hwmon(root, chips):
    for i, files in enumerate(chips):
        d = root / f"hwmon{i}"
        d.mkdir()
        for name, value in files.items():
            (d / name).write_text(str(value))
    return str(root)


def test_hwmon_jetson(tmp_path):
    """Fan split across pwmfan/pwm_tach, ina3221 rails, unlabeled sum channel ignored."""
    temps, power, fans = hwmon_sensors(root=fake_hwmon(tmp_path, [
        {"name": "pwmfan", "pwm1": 76},
        {"name": "ina3221", "in1_label": "VDD_IN", "in1_input": 5000, "curr1_input": 1200,
         "in4_input": 6400, "curr4_input": 2416},
        {"name": "pwm_tach", "rpm": 1636},
    ]))
    assert temps == {}
    assert power == {"VDD_IN": 6.0}
    assert fans == [{"name": "pwmfan", "rpm": None, "percent": 30},
                    {"name": "pwm_tach", "rpm": 1636, "percent": None}]


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
