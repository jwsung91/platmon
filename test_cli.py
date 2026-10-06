import pytest

from cli import render

FULL = {
    "platform": "Jetson Orin", "model": "Test Board", "uptime": 90061, "power_mode": "MAXN_SUPER",
    "cpu": [{"usage": 12.5, "freq": 1728000000}, {"usage": 0.0, "freq": 729600000}],
    "gpu": {"usage": 50.0, "freq": 306000000, "max_freq": 1020000000},
    "memory": {"total": 8 * 2**30, "used": 2 * 2**30, "swap_total": 4 * 2**30, "swap_used": 0},
    "disk": {"total": 100 * 2**30, "used": 25 * 2**30},
    "temperature": {"cpu": 51.2},
    "power": {"VDD_IN": 4.82},
    "fans": [{"name": "pwmfan", "rpm": None, "percent": 31}, {"name": "pwm_tach", "rpm": 1741, "percent": None}],
}

# bare Linux host (e.g. WSL): no GPU, power mode, cpufreq, swap or sensors
BARE = dict(FULL, platform="Linux", power_mode=None, gpu=None, temperature={}, power={}, fans=[],
            cpu=[{"usage": 3.0, "freq": None}],
            memory={"total": 8 * 2**30, "used": 2 * 2**30, "swap_total": 0, "swap_used": 0})


@pytest.mark.parametrize("expected", [
    "Jetson Orin   mode MAXN_SUPER   up 1d 01:01",
    "12.5%  1728 MHz",
    "50.0%   306 MHz",
    "RAM   █████··············· 2.0G/8.0G",
    "SWAP  ",
    "cpu 51.2°C",
    "VDD_IN 4.82W",
    "FAN   pwmfan  31%",
    "FAN   pwm_tach  1741 rpm",
])
def test_render_full(expected):
    assert expected in render(FULL)


def test_render_bare_shows_basics():
    out = render(BARE)
    assert "Linux   up 1d 01:01" in out
    assert "CPU0  " in out and "DISK  " in out


@pytest.mark.parametrize("absent", ["mode", "MHz", "GPU", "SWAP", "TEMP", "POWER", "FAN"])
def test_render_bare_hides_missing(absent):
    assert absent not in render(BARE)
