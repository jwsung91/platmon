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


CLI = str(__import__("pathlib").Path(__file__).parent.parent / "frontends" / "cli.py")


def run_cli(*args):
    import subprocess
    import sys
    return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True, timeout=20)


def test_once_prints_one_snapshot():
    from test_server import serve
    httpd, base = serve(FULL)
    try:
        r = run_cli("--once", base.removeprefix("http://"))
    finally:
        httpd.shutdown()
    assert r.returncode == 0
    assert r.stdout.startswith("Test Board\n") and "\033[" not in r.stdout  # no screen clearing


def test_not_running_explains_and_exits():
    import socket
    with socket.socket() as s:  # a port nothing listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    r = run_cli(f"localhost:{port}")  # without --once too: fail once, no endless retry loop
    assert r.returncode == 1
    assert f"platmon is not running on localhost:{port}" in r.stderr and "scripts/docker/start.sh" in r.stderr


def test_no_current_data_is_explained():
    from test_server import serve
    httpd, base = serve(None)  # service up, but no snapshot: 503
    try:
        r = run_cli("--once", base.removeprefix("http://"))
    finally:
        httpd.shutdown()
    assert r.returncode == 1 and "answered 503" in r.stderr and "no current data" in r.stderr


def test_render_unreadable_gpu_clock_and_fan():
    """None means "could not read": no 0 MHz / 0 rpm, and no crash."""
    out = render(dict(FULL, gpu={"usage": 50.0, "freq": None, "max_freq": None},
                      fans=[{"name": "CPU fan", "rpm": None, "percent": None}]))
    assert "GPU   " in out and "50.0%" in out and "MHz" not in out.split("GPU")[1].split("\n")[0]
    assert "FAN   CPU fan  n/a" in out
