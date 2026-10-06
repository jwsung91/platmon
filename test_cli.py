from cli import render

full = {
    "platform": "Jetson Orin", "model": "Test Board", "uptime": 90061, "power_mode": "MAXN_SUPER",
    "cpu": [{"usage": 12.5, "freq": 1728000000}, {"usage": 0.0, "freq": 729600000}],
    "gpu": {"usage": 50.0, "freq": 306000000, "max_freq": 1020000000},
    "memory": {"total": 8 * 2**30, "used": 2 * 2**30, "swap_total": 4 * 2**30, "swap_used": 0},
    "disk": {"total": 100 * 2**30, "used": 25 * 2**30},
    "temperature": {"cpu": 51.2},
    "power": {"VDD_IN": 4.82},
    "fans": [{"name": "pwmfan", "rpm": None, "percent": 31}, {"name": "pwm_tach", "rpm": 1741, "percent": None}],
}
out = render(full)
assert "Jetson Orin   mode MAXN_SUPER   up 1d 01:01" in out, out
assert "CPU0  " in out and "12.5%  1728 MHz" in out
assert "GPU   " in out and "50.0%   306 MHz" in out
assert "RAM   █████··············· 2.0G/8.0G" in out
assert "SWAP  " in out
assert "cpu 51.2°C" in out and "VDD_IN 4.82W" in out
assert "FAN   pwmfan  31%" in out and "FAN   pwm_tach  1741 rpm" in out

# bare Linux host (e.g. WSL): no GPU, power mode, cpufreq, swap or sensors
bare = dict(full, platform="Linux", power_mode=None, gpu=None, temperature={}, power={}, fans=[],
            cpu=[{"usage": 3.0, "freq": None}],
            memory={"total": 8 * 2**30, "used": 2 * 2**30, "swap_total": 0, "swap_used": 0})
out = render(bare)
assert "mode" not in out and "MHz" not in out
for absent in ("GPU", "SWAP", "TEMP", "POWER", "FAN"):
    assert absent not in out, absent
assert "Linux   up 1d 01:01" in out and "CPU0  " in out and "DISK  " in out
print("ok")
