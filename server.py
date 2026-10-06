#!/usr/bin/env python3
"""platmon collector (Jetson, Raspberry Pi, PC, Linux). Serves JSON at /api/stats and the web viewer at /.

Usage: python3 server.py [port]   (default 8080)
"""
import glob
import json
import os
import re
import shutil
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def hwmon_sensors(skip=(), root="/sys/class/hwmon"):
    """Temps, power and fans from every hwmon chip. skip: chip names already read elsewhere."""
    temps, power, fans = {}, {}, []
    for d in sorted(glob.glob(f"{root}/hwmon*")):
        chip = read(f"{d}/name", "")
        if chip in skip:
            continue

        def idx(pattern):
            return sorted(int(re.search(r"(\d+)_", os.path.basename(p)).group(1))
                          for p in glob.glob(f"{d}/{pattern}"))

        def label(kind, n):
            return read(f"{d}/{kind}{n}_label") or f"{chip} {kind}{n}"

        for n in idx("temp*_input"):
            t = read(f"{d}/temp{n}_input")
            if t:
                key = f"{chip} {read(f'{d}/temp{n}_label') or f'temp{n}'}"
                if key in temps:  # e.g. two nvme drives both report "Composite"
                    key += f" ({os.path.basename(d)})"
                temps[key] = int(t) / 1000  # m°C
        for n in idx("power*_input"):
            p = read(f"{d}/power{n}_input")
            if p:
                power[label("power", n)] = round(int(p) / 1e6, 2)  # µW
        for n in idx("curr*_input"):  # ina3221-style rails; label required, unlabeled channels are sums
            mv, ma, lbl = read(f"{d}/in{n}_input"), read(f"{d}/curr{n}_input"), read(f"{d}/in{n}_label")
            if mv and ma and lbl:
                power[lbl] = round(int(mv) * int(ma) / 1e6, 2)  # mV*mA -> W

        fan_idx = idx("fan*_input")
        for n in fan_idx:
            pwm = read(f"{d}/pwm{n}")
            fans.append({"name": label("fan", n), "rpm": int(read(f"{d}/fan{n}_input", 0)),
                         "percent": round(int(pwm) * 100 / 255) if pwm else None})
        if not fan_idx:  # Jetson splits one fan into pwmfan (pwm1 only) and pwm_tach (non-standard "rpm")
            rpm = read(f"{d}/rpm")
            if rpm:
                fans.append({"name": chip, "rpm": int(rpm), "percent": None})
            pwm = read(f"{d}/pwm1")
            if pwm:
                fans.append({"name": chip, "rpm": None, "percent": round(int(pwm) * 100 / 255)})
    return temps, power, fans


def cpu_times():
    with open("/proc/stat") as f:
        return [list(map(int, l.split()[1:])) for l in f if re.match(r"cpu\d", l)]


def cpu_percent(before, after):
    """Busy % per core from two /proc/stat samples (idle + iowait count as idle)."""
    out = []
    for b, a in zip(before, after):
        total = sum(a) - sum(b)
        idle = (a[3] + a[4]) - (b[3] + b[4])
        out.append(round(100 * (total - idle) / total, 1) if total else 0.0)
    return out


def meminfo():
    m = {}
    with open("/proc/meminfo") as f:
        for l in f:
            k, v = l.split(":")
            m[k] = int(v.split()[0]) * 1024
    return m


def power_mode_name(mode_id, conf_text):
    m = re.search(rf"POWER_MODEL\s+ID={mode_id}\s+NAME=(\S+?)\s*>", conf_text or "")
    return m.group(1) if m else mode_id


def detect_platform(compatible, has_dmi):
    """compatible: /proc/device-tree/compatible (NUL-separated), empty on x86."""
    for key, name in (("nvidia,tegra234", "Jetson Orin"), ("nvidia,tegra194", "Jetson Xavier"),
                      ("nvidia,tegra", "Jetson"), ("raspberrypi", "Raspberry Pi")):
        if key in compatible:
            return name
    return "PC" if has_dmi else "Linux"


PLATFORM = detect_platform(read("/proc/device-tree/compatible", ""), os.path.isdir("/sys/class/dmi/id"))


def collect():
    t0 = cpu_times()
    time.sleep(0.25)  # ponytail: per-request sampling, fine for a few viewers; add a background sampler if many
    cpu = cpu_percent(t0, cpu_times())
    freqs = [read(f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq") for i in range(len(cpu))]
    freqs = [int(f) * 1000 if f else None for f in freqs]

    temps, zone_types = {}, set()
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*"), key=lambda p: int(p.rsplit("e", 1)[1])):
        zt = read(f"{z}/type")
        zone_types.add(zt)
        t = read(f"{z}/temp")  # inactive zones (cv*) return ENODATA
        if t:
            temps[zt.removesuffix("-thermal")] = int(t) / 1000
    # chips like acpitz also show up as thermal zones; skip them to avoid duplicates
    hw_temps, power, fans = hwmon_sensors(skip=zone_types)
    temps.update(hw_temps)

    mem = meminfo()
    disk = shutil.disk_usage("/")
    mode = read("/var/lib/nvpmodel/status")  # Jetson only
    gpu_load = read("/sys/devices/platform/gpu.0/load")  # Jetson only, per-mille

    return {
        "time": time.time(),
        "platform": PLATFORM,
        "model": (read("/proc/device-tree/model") or read("/sys/class/dmi/id/product_name")
                  or os.uname().nodename).rstrip("\0"),
        "uptime": float(read("/proc/uptime").split()[0]),
        "power_mode": power_mode_name(mode.removeprefix("pmode:").lstrip("0") or "0",
                                      read("/etc/nvpmodel.conf")) if mode else None,
        "cpu": [{"usage": u, "freq": f} for u, f in zip(cpu, freqs)],
        "gpu": {
            "usage": int(gpu_load) / 10,
            "freq": int(read("/sys/class/devfreq/17000000.gpu/cur_freq", 0)),
            "max_freq": int(read("/sys/class/devfreq/17000000.gpu/max_freq", 0)),
        } if gpu_load else None,
        "memory": {"total": mem["MemTotal"], "used": mem["MemTotal"] - mem["MemAvailable"],
                   "swap_total": mem["SwapTotal"], "swap_used": mem["SwapTotal"] - mem["SwapFree"]},
        "disk": {"total": disk.total, "used": disk.used},
        "temperature": temps,
        "power": power,
        "fans": fans,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/stats":
            body, ctype = json.dumps(collect()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            with open(os.path.join(WEB_DIR, "index.html"), "rb") as f:
                body, ctype = f.read(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"platmon on :{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
