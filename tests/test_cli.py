import pytest

from frontends.cli import render
from collector import collect

FULL = {
    "platform": "Jetson Orin", "model": "Test Board", "uptime": 90061, "power_mode": "MAXN_SUPER",
    "system": {"os": "Ubuntu 22.04.5 LTS", "kernel": "5.15.199-tegra", "arch": "aarch64", "hostname": "orin",
               "l4t": "R36.5.2"},
    "cpu": [{"id": 0, "usage": 12.5, "freq": 1728000000}, {"id": 2, "usage": 0.0, "freq": 729600000}],
    "gpu": {"usage": 50.0, "freq": 306000000, "max_freq": 1020000000},
    "memory": {"total": 8 * 2**30, "used": 2 * 2**30, "swap_total": 4 * 2**30, "swap_used": 0},
    "disk": {"total": 100 * 2**30, "used": 25 * 2**30},
    "temperature": {"cpu": 51.2},
    "power": {"VDD_IN": 4.82},
    "fans": [{"name": "pwmfan", "rpm": None, "percent": 31}, {"name": "pwm_tach", "rpm": 1741, "percent": None}],
}

# bare Linux host (e.g. WSL): no GPU, power mode, cpufreq, swap or sensors
BARE = dict(FULL, platform="Linux", power_mode=None, gpu=None, temperature={}, power={}, fans=[],
            cpu=[{"id": 0, "usage": 3.0, "freq": None}],
            memory={"total": 8 * 2**30, "used": 2 * 2**30, "swap_total": 0, "swap_used": 0})


@pytest.mark.parametrize("expected", [
    "Jetson Orin   mode MAXN_SUPER   up 1d 01:01",
    "Ubuntu 22.04.5 LTS · kernel 5.15.199-tegra · aarch64 · host orin · L4T R36.5.2",
    "12.5%  1728 MHz",
    "CPU2  ",  # labelled by core id, not position (cpu1 offline)
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


def test_render_live_collect():
    """The viewer accepts whatever the collector really returns on this host (CI runner, WSL, boards)."""
    s = collect()
    out = render(s)
    assert s["platform"] in out
    assert all(f"CPU{c['id']}" in out for c in s["cpu"])


def test_render_server_without_system_info():
    """An older server has no "system" entry: no system line, no empty extra line."""
    old = {k: v for k, v in FULL.items() if k != "system"}
    assert render(old).split("\n")[:3] == ["Test Board", "Jetson Orin   mode MAXN_SUPER   up 1d 01:01", ""]


def test_render_unknown_system_entry():
    """Entries added by a future board module show up as "key value" without changing the viewer."""
    assert "firmware 1.2" in render(dict(FULL, system={"os": "X", "firmware": "1.2"}))
