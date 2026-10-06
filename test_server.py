from server import cpu_percent, detect_platform, power_mode_name

# user nice system idle iowait irq softirq steal
assert cpu_percent([[100, 0, 100, 700, 100, 0, 0, 0]], [[150, 0, 150, 800, 100, 0, 0, 0]]) == [50.0]
assert cpu_percent([[1, 1, 1, 1, 1]], [[1, 1, 1, 1, 1]]) == [0.0]  # no ticks elapsed

conf = "< POWER_MODEL ID=0 NAME=15W >\n< POWER_MODEL ID=2 NAME=MAXN_SUPER >"
assert power_mode_name("2", conf) == "MAXN_SUPER"
assert power_mode_name("9", conf) == "9"

assert detect_platform("nvidia,p3767-0005\0nvidia,tegra234", False) == "Jetson Orin"
assert detect_platform("raspberrypi,5-model-b\0brcm,bcm2712", False) == "Raspberry Pi"
assert detect_platform("", True) == "PC"
assert detect_platform("rockchip,rk3588", False) == "Linux"

# hwmon_sensors against fake sysfs trees
import os
import tempfile
from server import hwmon_sensors


def tree(chips):
    root = tempfile.mkdtemp()
    for i, files in enumerate(chips):
        d = os.path.join(root, f"hwmon{i}")
        os.mkdir(d)
        for k, v in files.items():
            with open(os.path.join(d, k), "w") as f:
                f.write(str(v))
    return root


# Jetson Orin: fan split across pwmfan/pwm_tach, ina3221 rails, unlabeled sum channel ignored
temps, power, fans = hwmon_sensors(root=tree([
    {"name": "pwmfan", "pwm1": 76},
    {"name": "ina3221", "in1_label": "VDD_IN", "in1_input": 5000, "curr1_input": 1200,
     "in4_input": 6400, "curr4_input": 2416},
    {"name": "pwm_tach", "rpm": 1636},
]))
assert temps == {}
assert power == {"VDD_IN": 6.0}
assert fans == [{"name": "pwmfan", "rpm": None, "percent": 30},
                {"name": "pwm_tach", "rpm": 1636, "percent": None}]

# x86 PC: acpitz skipped (already a thermal zone), duplicate nvme labels kept apart, fan with pwm
temps, power, fans = hwmon_sensors(skip={"acpitz"}, root=tree([
    {"name": "acpitz", "temp1_input": 27800},
    {"name": "coretemp", "temp1_label": "Package id 0", "temp1_input": 45000},
    {"name": "nvme", "temp1_label": "Composite", "temp1_input": 38850},
    {"name": "nvme", "temp1_label": "Composite", "temp1_input": 41850},
    {"name": "nct6775", "fan2_input": 950, "pwm2": 128, "power1_input": 12500000},
]))
assert temps == {"coretemp Package id 0": 45.0, "nvme Composite": 38.85,
                 "nvme Composite (hwmon3)": 41.85}, temps
assert power == {"nct6775 power1": 12.5}
assert fans == [{"name": "nct6775 fan2", "rpm": 950, "percent": 50}]
print("ok")
