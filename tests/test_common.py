import pytest

from collector import detect, jetson
from collector.common import cpu_percent, hwmon_sensors, os_release, thermal_zones


@pytest.mark.parametrize("before, after, expected", [
    # user nice system idle iowait irq softirq steal
    ({0: [100, 0, 100, 700, 100, 0, 0, 0]}, {0: [150, 0, 150, 800, 100, 0, 0, 0]}, {0: 50.0}),
    ({0: [1, 1, 1, 1, 1]}, {0: [1, 1, 1, 1, 1]}, {0: 0.0}),  # no ticks elapsed
    # cpu1 offline, cpu3 went offline between samples: ids kept, nothing mispaired
    ({0: [0, 0, 0, 0, 0], 2: [0, 0, 0, 0, 0], 3: [0, 0, 0, 0, 0]},
     {0: [10, 0, 0, 10, 0], 2: [0, 0, 0, 10, 0]}, {0: 50.0, 2: 0.0}),
    # VM host: guest (and guest_nice) time is already included in user (and nice); not counted twice
    #  user nice system idle iowait irq softirq steal guest guest_nice
    ({0: [0] * 10}, {0: [50, 0, 0, 50, 0, 0, 0, 0, 50, 0]}, {0: 50.0}),
    ({0: [0] * 10}, {0: [0, 50, 0, 50, 0, 0, 0, 0, 0, 50]}, {0: 50.0}),
])
def test_cpu_percent(before, after, expected):
    assert cpu_percent(before, after) == expected


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
