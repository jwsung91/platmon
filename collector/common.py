"""Collectors for any Linux host: standard /proc, cpufreq, thermal and hwmon interfaces only.

Board-specific paths and tools belong in a board module (see jetson.py).
"""
import glob
import os
import re
import shutil
import time

from .sysfs import DEVICE_TREE, HOST_ROOT, host_path, hwmon_chips, numbered, read, read_int


def unique_key(table, key, d):
    """key, or "key (hwmonN)" when another chip already reported the same name (two nvme drives, two ina219s)."""
    return f"{key} ({os.path.basename(d)})" if key in table else key


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
                key = unique_key(temps, f"{chip} {read(f'{d}/temp{n}_label') or f'temp{n}'}", d)
                temps[key] = int(t) / 1000  # m°C
        for n in numbered(d, "power*_input"):
            p = read(f"{d}/power{n}_input")
            if p:
                power[unique_key(power, label("power", n), d)] = round(int(p) / 1e6, 2)  # µW
        for n in numbered(d, "curr*_input"):  # ina3221-style rails; label required, unlabeled channels are sums
            mv, ma, lbl = read(f"{d}/in{n}_input"), read(f"{d}/curr{n}_input"), read(f"{d}/in{n}_label")
            if mv and ma and lbl:
                power[unique_key(power, lbl, d)] = round(int(mv) * int(ma) / 1e6, 2)  # mV*mA -> W

        fan_idx = numbered(d, "fan*_input")
        for n in fan_idx:
            pwm = read(f"{d}/pwm{n}")
            fans.append({"name": label("fan", n), "rpm": read_int(f"{d}/fan{n}_input"),  # None if unreadable, not 0
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


def cpu_times(path="/proc/stat"):
    """{cpu id: jiffies} for online cores; offline cores are absent from /proc/stat."""
    with open(path) as f:
        times = {int(m.group(1)): list(map(int, l.split()[1:])) for l in f if (m := re.match(r"cpu(\d+)", l))}
    if not times:  # never a host with 0 CPUs: the file could not be read as expected
        raise ValueError("no per-cpu lines in /proc/stat")
    return times


def cpu_percent(before, after):
    """Busy % per core id from two /proc/stat samples (idle + iowait count as idle), and why the other cores
    of `after` have none: {id: usage}, {id: reason}. Cores gone in `after` are left out.
    Only user..steal (the first 8 fields) make up the total: guest and guest_nice are already counted
    in user and nice, so adding them again overstates the load on hosts running virtual machines."""
    usage, unavailable = {}, {}
    for n in sorted(after):
        if n not in before:  # new, or back online: no earlier reading of this core to compare with
            unavailable[n] = "warmup"
            continue
        delta = [a - b for a, b in zip(after[n][:8], before[n][:8])]
        total, idle = sum(delta), delta[3] + delta[4]
        if any(d < 0 for d in delta):  # e.g. iowait can go backwards; not a reboot, not 0 %, just unusable
            unavailable[n] = "counter_regressed"
        elif not total:  # nothing measured, which is not the same as measured idle
            unavailable[n] = "no_ticks"
        else:
            usage[n] = round(100 * (total - idle) / total, 1)
    return usage, unavailable


class CpuCounters:
    """CPU usage from consecutive /proc/stat readings: each sample() reads it once and compares with the
    previous successful reading, so a running service needs no wait inside its collection.
    The usage is the busy share of the ticks between the two readings, over window_ms."""

    def __init__(self, clock=time.monotonic_ns, max_gap=None, mode="interval"):
        """clock: elapsed nanoseconds (the service passes the Sampler's); max_gap: seconds, a longer window
        between readings is not averaged over (None: no limit)."""
        self._clock, self.mode = clock, mode
        self._max_gap = None if max_gap is None else round(max_gap * 1e9)
        self._last = None  # (elapsed ns when the reading began, cpu_times()) of the last successful reading

    def sample(self):
        """({id: usage}, cpu_sampling). Every successful reading becomes the next baseline, whatever the
        result; a failed one clears the baseline and raises, so the collection fails and restarts warmup."""
        try:
            now = self._clock()
            times = cpu_times()
        except Exception:
            self._last = None
            raise
        last, self._last = self._last, (now, times)
        window = None if last is None else now - last[0]
        if last is None:
            usage, unavailable = {}, dict.fromkeys(times, "warmup")
        elif window <= 0:
            usage, unavailable, window = {}, dict.fromkeys(times, "invalid_interval"), None
        elif self._max_gap is not None and window > self._max_gap:
            usage, unavailable = {}, dict.fromkeys(times, "gap")
        else:
            usage, unavailable = cpu_percent(last[1], times)
        return usage, {"mode": self.mode, "window_ms": None if window is None else round(window / 1e6, 3),
                       "unavailable": [{"id": n, "reason": r} for n, r in sorted(unavailable.items())]}


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


def collect(cpu=None):
    """Fields every host has. gpu and power_mode stay None unless a board module fills them.
    cpu: the service's CpuCounters. Without one (a one-off call) the CPU usage comes from two readings
    250 ms apart with a baseline of its own."""
    if cpu is None:
        cpu = CpuCounters(mode="oneshot")
        cpu.sample()
        time.sleep(0.25)
    usage, sampling = cpu.sample()
    freqs = {n: read_int(f"/sys/devices/system/cpu/cpu{n}/cpufreq/scaling_cur_freq") for n in usage}

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
        "cpu": [{"id": n, "usage": u, "freq": freqs[n] * 1000 if freqs[n] else None} for n, u in usage.items()],
        "cpu_sampling": sampling,  # cores missing from cpu, and why
        "gpu": None,
        "memory": {"total": mem["MemTotal"], "used": mem["MemTotal"] - mem["MemAvailable"],
                   "swap_total": mem["SwapTotal"], "swap_used": mem["SwapTotal"] - mem["SwapFree"]},
        "disk": {"total": disk.total, "used": disk.used},
        "temperature": temps,
        "power": power,
        "fans": fans,
    }
