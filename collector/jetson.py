"""Jetson-only data: GPU load and clock, nvpmodel power mode, pwm_tach fan speed, L4T release."""
import re

from .sysfs import host_path, hwmon_chips, read, read_int


def gpu(root="/sys"):
    load = read(f"{root}/devices/platform/gpu.0/load")  # per-mille
    if not load:
        return None
    devfreq = f"{root}/class/devfreq/17000000.gpu"  # Orin; unverified on Xavier
    return {"usage": int(load) / 10, "freq": read_int(f"{devfreq}/cur_freq", 0),
            "max_freq": read_int(f"{devfreq}/max_freq", 0)}


def power_mode(status, conf_text):
    """status: /var/lib/nvpmodel/status ("pmode:0002"), conf_text: /etc/nvpmodel.conf."""
    mode_id = status.removeprefix("pmode:").lstrip("0") or "0"
    m = re.search(rf"POWER_MODEL\s+ID={mode_id}\s+NAME=(\S+?)\s*>", conf_text or "")
    return m.group(1) if m else mode_id


def l4t(text):
    """/etc/nv_tegra_release ("# R36 (release), REVISION: 5.2, ...") -> "R36.5.2"."""
    m = re.search(r"R(\d+) \(release\), REVISION: ([\d.]+)", text or "")
    return f"R{m.group(1)}.{m.group(2)}" if m else None


def tach_fans(root="/sys/class/hwmon"):
    """pwm_tach reports fan speed in a non-standard "rpm" file; its pwm half is the pwmfan chip."""
    fans = []
    for d, chip in hwmon_chips(root):
        rpm = read_int(f"{d}/rpm")
        if rpm is not None:
            fans.append({"name": chip, "rpm": rpm, "percent": None})
    return fans


def extend(stats):
    status = read("/var/lib/nvpmodel/status")
    stats["power_mode"] = power_mode(status, read("/etc/nvpmodel.conf")) if status else None
    stats["gpu"] = gpu()
    stats["fans"] += tach_fans()
    release = l4t(read(host_path("/etc/nv_tegra_release")))
    if release:
        stats["system"]["l4t"] = release
