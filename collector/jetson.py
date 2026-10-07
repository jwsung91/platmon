"""Jetson-only data: GPU load and clock, nvpmodel power mode, pwm_tach fan speed, L4T release."""
import glob
import os
import re

from . import sysfs
from .sysfs import guard, host_path, hwmon_chips, read


# GPU devfreq device names per BSP (NVIDIA L4T docs): Orin R36 17000000.gpu (verified on an Orin Nano),
# Orin R35 17000000.ga10b, Xavier 17000000.gv11b, TX2 17000000.gp10b, Nano 57000000.gpu.
GPU_DEVFREQ = ("*.gpu", "*.ga10b", "*.gv11b", "*.gp10b", "*.gm20b")
# load (per-mille) sits in the GPU device directory; gpu.0 links to it where devfreq is not found
GPU_LOAD = ("devices/platform/gpu.0/load", "devices/gpu.0/load")


def gpu(root="/sys", group=None):
    """GPU load and clocks. freq/max_freq are None (not 0) when the clock cannot be read.
    The load comes from the first candidate that reads; the others' failures only count if none does."""
    g = group or sysfs.Group("gpu")
    devfreq = next((p for pattern in GPU_DEVFREQ for p in sorted(glob.glob(f"{root}/class/devfreq/{pattern}"))), None)
    loads = ([f"{devfreq}/device/load"] if devfreq else []) + [f"{root}/{p}" for p in GPU_LOAD]
    tried = sysfs.Group("gpu")
    load = next((v for v in (tried.read(p, "load") for p in loads) if v is not None), None)
    if load is None:
        for issue, detail in zip(tried.issues, tried.details):
            g.note(issue["target"], issue["reason"], detail)
        g.reasons |= tried.reasons
        return None

    def clock(name):
        return None if devfreq is None else g.read(f"{devfreq}/{name}", name, found=devfreq)

    out = {"usage": g.got(load / 10), "freq": clock("cur_freq"), "max_freq": clock("max_freq")}
    for k in ("freq", "max_freq"):
        if out[k] is not None:
            g.got(out[k])
    return out


def pmode(text):
    """The /var/lib/nvpmodel/status line ("pmode:0002") as it is; ValueError if it is not one."""
    if not re.fullmatch(r"pmode:\d+", text):
        raise ValueError(text)
    return text


def power_mode(status, conf_text):
    """status: /var/lib/nvpmodel/status ("pmode:0002"), conf_text: /etc/nvpmodel.conf."""
    mode_id = status.removeprefix("pmode:").lstrip("0") or "0"
    m = re.search(rf"POWER_MODEL\s+ID={mode_id}\s+NAME=(\S+?)\s*>", conf_text or "")
    return m.group(1) if m else mode_id


def l4t(text):
    """/etc/nv_tegra_release ("# R36 (release), REVISION: 5.2, ...") -> "R36.5.2"."""
    m = re.search(r"R(\d+) \(release\), REVISION: ([\d.]+)", text or "")
    return f"R{m.group(1)}.{m.group(2)}" if m else None


def l4t_release(text):
    """l4t() for a file that must hold the release line; ValueError otherwise."""
    release = l4t(text)
    if release is None:
        raise ValueError("no release line")
    return release


def tach_fans(root="/sys/class/hwmon", group=None):
    """pwm_tach reports fan speed in a non-standard "rpm" file; its pwm half is the pwmfan chip.
    A chip with an rpm file that cannot be read is still listed, with rpm None."""
    g = group or sysfs.Group("fans")
    fans = []
    with guard(g):
        for d, chip in hwmon_chips(root):
            if not os.path.exists(f"{d}/rpm"):
                continue
            rpm = g.read(f"{d}/rpm", f"{os.path.basename(d)}.rpm", found=f"{d}/rpm")
            fans.append({"name": chip, "rpm": None if rpm is None else g.got(rpm), "percent": None})
    return fans


def extend(stats, groups=None):
    """Fills the Jetson fields; each part notes in its group what it could not read."""
    g = groups or sysfs.groups("gpu", "fans", "power_mode", "board_info")
    stats["power_mode"] = stats["gpu"] = None
    with guard(g["power_mode"]):
        status = g["power_mode"].read("/var/lib/nvpmodel/status", "status", parse=pmode)
        if status is not None:
            stats["power_mode"] = g["power_mode"].got(power_mode(status, read("/etc/nvpmodel.conf")))
    with guard(g["gpu"]):
        stats["gpu"] = gpu(group=g["gpu"])
    stats["fans"] += tach_fans(group=g["fans"])
    with guard(g["board_info"]):
        release = g["board_info"].read(host_path("/etc/nv_tegra_release"), "l4t", parse=l4t_release)
        if release is not None:
            stats["system"]["l4t"] = g["board_info"].got(release)
