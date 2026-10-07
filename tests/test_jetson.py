import pytest

from collector import jetson
from test_common import fake_hwmon


@pytest.mark.parametrize("status, expected", [("pmode:0002", "MAXN_SUPER"), ("pmode:0000", "15W"), ("pmode:0009", "9")])
def test_power_mode(status, expected):
    conf = "< POWER_MODEL ID=0 NAME=15W >\n< POWER_MODEL ID=2 NAME=MAXN_SUPER >"
    assert jetson.power_mode(status, conf) == expected


def test_tach_fans(tmp_path):
    """Only chips with the non-standard rpm file count; the pwmfan half is common hwmon's job."""
    root = fake_hwmon(tmp_path, [{"name": "pwmfan", "pwm1": 76}, {"name": "pwm_tach", "rpm": 1636}])
    assert jetson.tach_fans(root) == [{"name": "pwm_tach", "rpm": 1636, "percent": None}]


def test_gpu(tmp_path):
    assert jetson.gpu(str(tmp_path)) is None  # no gpu.0/load: not reported
    for path, value in [("devices/platform/gpu.0/load", 500), ("class/devfreq/17000000.gpu/cur_freq", 306000000),
                        ("class/devfreq/17000000.gpu/max_freq", 1020000000)]:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(str(value))
    assert jetson.gpu(str(tmp_path)) == {"usage": 50.0, "freq": 306000000, "max_freq": 1020000000}


@pytest.mark.parametrize("text, expected", [
    ("# R36 (release), REVISION: 5.2, GCID: 46426093, BOARD: generic, EABI: aarch64, DATE: Thu Jul 16", "R36.5.2"),
    ("# R35 (release), REVISION: 4.1, GCID: 33958178, BOARD: t186ref", "R35.4.1"),
    ("garbage", None),
    (None, None),
])
def test_l4t(text, expected):
    assert jetson.l4t(text) == expected
