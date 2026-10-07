"""Jetson-only data: GPU load and clock, nvpmodel power mode, pwm_tach fan speed, L4T release."""
import glob
import re

from .sysfs import host_path, hwmon_chips, read, read_int


# GPU devfreq device names per BSP (NVIDIA L4T docs): Orin R36 17000000.gpu (verified on an Orin Nano),
# Orin R35 17000000.ga10b, Xavier 17000000.gv11b, TX2 17000000.gp10b, Nano 57000000.gpu.
GPU_DEVFREQ = ("*.gpu", "*.ga10b", "*.gv11b", "*.gp10b", "*.gm20b")
# load (per-mille) sits in the GPU device directory; gpu.0 links to it where devfreq is not found
GPU_LOAD = ("devices/platform/gpu.0/load", "devices/gpu.0/load")


def gpu(root="/sys"):
    """GPU load and clocks. freq/max_freq are None (not 0) when the clock cannot be read."""
    devfreq = next((p for pattern in GPU_DEVFREQ for p in sorted(glob.glob(f"{root}/class/devfreq/{pattern}"))), None)
    loads = ([f"{devfreq}/device/load"] if devfreq else []) + [f"{root}/{p}" for p in GPU_LOAD]
    load = next((v for v in map(read_int, loads) if v is not None), None)
    if load is None:
        return None
    return {"usage": load / 10,
            "freq": read_int(f"{devfreq}/cur_freq") if devfreq else None,
            "max_freq": read_int(f"{devfreq}/max_freq") if devfreq else None}


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
