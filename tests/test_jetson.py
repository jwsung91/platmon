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


def make(root, files):
    for path, value in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(str(value))


@pytest.mark.parametrize("files, expected", [
    # Orin R35 names the GPU devfreq device 17000000.ga10b; load sits in its device directory
    ({"class/devfreq/17000000.ga10b/cur_freq": 306000000, "class/devfreq/17000000.ga10b/max_freq": 1300500000,
      "class/devfreq/17000000.ga10b/device/load": 250},
     {"usage": 25.0, "freq": 306000000, "max_freq": 1300500000}),
    # Xavier: 17000000.gv11b, load through /sys/devices/gpu.0
    ({"class/devfreq/17000000.gv11b/cur_freq": 114750000, "class/devfreq/17000000.gv11b/max_freq": 1377000000,
      "devices/gpu.0/load": 500},
     {"usage": 50.0, "freq": 114750000, "max_freq": 1377000000}),
    # load readable but no GPU devfreq device: clock unknown (None), not 0 MHz
    ({"devices/platform/gpu.0/load": 500}, {"usage": 50.0, "freq": None, "max_freq": None}),
    # devfreq device without readable clock files
    ({"class/devfreq/17000000.gpu/device/load": 0}, {"usage": 0.0, "freq": None, "max_freq": None}),
])
def test_gpu_across_bsps(tmp_path, files, expected):
    make(tmp_path, files)
    assert jetson.gpu(str(tmp_path)) == expected
