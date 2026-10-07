"""Collectors for any Linux host: standard /proc, cpufreq, thermal and hwmon interfaces only.

Board-specific paths and tools belong in a board module (see jetson.py).
"""
import glob
import os
import re
import shutil
import time

from .sysfs import DEVICE_TREE, HOST_ROOT, host_path, hwmon_chips, numbered, read, read_int


def hwmon_sensors(skip=(), root="/sys/class/hwmon"):
    """Temps, power and fans from every hwmon chip. skip: chip names already read elsewhere."""
    temps, power, fans = {}, {}, []
    for d, chip in hwmon_chips(root):
        if chip in skip:
            continue

        def label(kind, n):
            return read(f"{d}/{kind}{n}_label") or f"{chip} {kind}{n}"

        for n in numbered(d, "temp*_input"):
            t = read(f"{d}/temp{n}_input")
            if t:
                key = f"{chip} {read(f'{d}/temp{n}_label') or f'temp{n}'}"
                if key in temps:  # e.g. two nvme drives both report "Composite"
                    key += f" ({os.path.basename(d)})"
                temps[key] = int(t) / 1000  # m°C
        for n in numbered(d, "power*_input"):
            p = read(f"{d}/power{n}_input")
            if p:
                power[label("power", n)] = round(int(p) / 1e6, 2)  # µW
        for n in numbered(d, "curr*_input"):  # ina3221-style rails; label required, unlabeled channels are sums
            mv, ma, lbl = read(f"{d}/in{n}_input"), read(f"{d}/curr{n}_input"), read(f"{d}/in{n}_label")
            if mv and ma and lbl:
                power[lbl] = round(int(mv) * int(ma) / 1e6, 2)  # mV*mA -> W

        fan_idx = numbered(d, "fan*_input")
        for n in fan_idx:
            pwm = read(f"{d}/pwm{n}")
            fans.append({"name": label("fan", n), "rpm": read_int(f"{d}/fan{n}_input", 0),
                         "percent": round(int(pwm) * 100 / 255) if pwm else None})
        pwm = read(f"{d}/pwm1")
        if not fan_idx and pwm:  # pwm-fan without a tachometer
            fans.append({"name": chip, "rpm": None, "percent": round(int(pwm) * 100 / 255)})
    return temps, power, fans


def thermal_zones(root="/sys/class/thermal"):
    """Zone temps, plus zone types as their hwmon twins name them (kernel turns "-" into "_")."""
    temps, zone_types = {}, set()
    for z in sorted(glob.glob(f"{root}/thermal_zone*"), key=lambda p: int(p.rsplit("e", 1)[1])):
        zt = read(f"{z}/type", "")
        zone_types.add(zt.replace("-", "_"))
        t = read(f"{z}/temp")  # inactive zones (cv*) return ENODATA
        if t:
            key = zt.removesuffix("-thermal")
            if key in temps:  # e.g. several acpitz zones
                key += f" ({os.path.basename(z)})"
            temps[key] = int(t) / 1000
    return temps, zone_types


def cpu_times():
    """{cpu id: jiffies} for online cores; offline cores are absent from /proc/stat."""
    with open("/proc/stat") as f:
        return {int(m.group(1)): list(map(int, l.split()[1:])) for l in f if (m := re.match(r"cpu(\d+)", l))}


def cpu_percent(before, after):
    """Busy % per core id from two /proc/stat samples (idle + iowait count as idle).
    Cores that went on/offline between the samples are left out."""
    out = {}
    for n in sorted(before.keys() & after.keys()):
        b, a = before[n], after[n]
        total = sum(a) - sum(b)
        idle = (a[3] + a[4]) - (b[3] + b[4])
        out[n] = round(100 * (total - idle) / total, 1) if total else 0.0
    return out


def meminfo():
    m = {}
    with open("/proc/meminfo") as f:
        for l in f:
            k, v = l.split(":")
            m[k] = int(v.split()[0]) * 1024
    return m


def os_release(text):
    """Distribution name from os-release text (freedesktop format): PRETTY_NAME, else NAME VERSION."""
    fields = {}
    for line in (text or "").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip("\"'")
    return fields.get("PRETTY_NAME") or " ".join(filter(None, (fields.get("NAME"), fields.get("VERSION")))) or None


def system_info():
    """OS of the host (read through HOST_ROOT, so a container reports the host, not its image), kernel, arch, hostname.
    Board modules may add their own entries (e.g. Jetson: l4t)."""
    u = os.uname()
    return {"os": os_release(read(host_path("/etc/os-release")) or read(host_path("/usr/lib/os-release"))),
            "kernel": u.release, "arch": u.machine, "hostname": u.nodename}


def collect():
    """Fields every host has. gpu and power_mode stay None unless a board module fills them."""
    t0 = cpu_times()
    time.sleep(0.25)  # ponytail: per-request sampling, fine for a few viewers; add a background sampler if many
    cpu = cpu_percent(t0, cpu_times())
    freqs = {n: read_int(f"/sys/devices/system/cpu/cpu{n}/cpufreq/scaling_cur_freq") for n in cpu}

    temps, zone_types = thermal_zones()
    # zones (acpitz, cpu-thermal, ...) also show up as hwmon chips; skip them to avoid duplicates
    hw_temps, power, fans = hwmon_sensors(skip=zone_types)
    temps.update(hw_temps)

    mem = meminfo()
    disk = shutil.disk_usage(HOST_ROOT)

    return {
        "time": time.time(),
        "model": (read(f"{DEVICE_TREE}/model") or read("/sys/class/dmi/id/product_name")
                  or os.uname().nodename).rstrip("\0"),
        "system": system_info(),
        "uptime": float(read("/proc/uptime").split()[0]),
        "power_mode": None,
        "cpu": [{"id": n, "usage": u, "freq": freqs[n] * 1000 if freqs[n] else None} for n, u in cpu.items()],
        "gpu": None,
        "memory": {"total": mem["MemTotal"], "used": mem["MemTotal"] - mem["MemAvailable"],
                   "swap_total": mem["SwapTotal"], "swap_used": mem["SwapTotal"] - mem["SwapFree"]},
        "disk": {"total": disk.total, "used": disk.used},
        "temperature": temps,
        "power": power,
        "fans": fans,
    }
