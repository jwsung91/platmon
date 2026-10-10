"""The live terminal view (screen()): fits the terminal, levels like the web page, plain without color."""
import re
from collections import deque

import pytest

from frontends import cli
from frontends.cli import (ANSI, LIMITS, Style, attention, busiest_first, data_age, fit, make_style, render, screen,
                           use_levels, vlen)
from test_cli import FULL

HOT = dict(FULL, cpu=[{"id": 0, "usage": 12.5, "freq": 1728000000}, {"id": 7, "usage": 91.4, "freq": 1728000000}],
           temperature={"cpu": 51.2, "tj": 86.2})
LIVE = {"state": "live", "age": 0.4, "error": None, "addr": "localhost:9797", "interval": 1.0}


def plain(lines):
    return [ANSI.sub("", line) for line in lines]


@pytest.mark.parametrize("width,height", [(119, 40), (79, 24), (60, 20), (40, 12)])
def test_fits_the_terminal(width, height):
    lines = screen(HOT, None, width, height, Style(), LIVE, {})
    assert len(lines) <= height
    assert all(vlen(line) <= width for line in lines)


def test_no_color_means_no_escapes():
    lines = screen(HOT, None, 119, 40, Style(color=False), LIVE, {})
    assert not any("\033" in line for line in lines)


def test_ascii_without_utf8():
    text = "\n".join(screen(HOT, None, 119, 40, Style(color=False, utf8=False), LIVE, {"CPU": deque([10, None, 90])}))
    assert not re.search(r"[^\x00-\x7f°·↓↑]", text)  # labels and units only; bars, rules and sparks are ASCII


def test_attention_follows_the_web_levels():
    # CPU mean 52 % is fine; tj 86.2 °C is a warning on Jetson Orin (85/95), not critical
    assert attention(HOT, None) == [("tj", "86.2 °C", "warn")]
    assert "NEEDS ATTENTION" in "\n".join(plain(screen(HOT, None, 119, 40, Style(), LIVE, {})))
    assert "NEEDS ATTENTION" not in "\n".join(plain(screen(FULL, None, 119, 40, Style(), LIVE, {})))


def test_offline_keeps_the_last_data():
    down = dict(LIVE, state="offline", age=47, error="cannot reach platmon at x:9797 (timed out)\n  check that its service runs")
    out = plain(screen(FULL, None, 119, 40, Style(), down, {}))
    assert "OFFLINE" in out[0] and "data 47 s old" in out[0]
    assert any("NOT CURRENT" in line for line in out)
    assert any(line.lstrip().startswith("RAM") for line in out)  # still there, dimmed


def test_too_short_says_what_was_left_out():
    out = plain(screen(HOT, None, 119, 14, Style(), LIVE, {}))
    assert len(out) == 14 and "more lines" in out[-3]


def test_fit_keeps_escapes_and_resets():
    st = Style()
    cut = fit(st("abcdef", "warn") + "ghij", 4)
    assert vlen(cut) == 4 and cut.endswith("\033[0m")


def test_server_levels_replace_the_defaults(monkeypatch):
    """/api/status "levels" ([thresholds]) as the web page uses them; bad or missing ones keep the defaults."""
    monkeypatch.setattr(cli, "LIMITS", dict(LIMITS))
    use_levels({"temperature": [80, 90], "memory": [10, 20], "cpu": [90, 80], "gpu": "x", "swap": [1, 2]})
    assert cli.LIMITS["memory"] == (10, 20) and cli.LIMITS["cpu"] == (80, 90) and cli.LIMITS["gpu"] == (80, 90)
    assert "swap" not in cli.LIMITS
    assert attention(HOT, None) == [("RAM", "25.0 %", "crit"), ("tj", "86.2 °C", "warn")]  # 80/90 replaces Orin's 85/95
    use_levels({"temperature": None})
    assert attention(HOT, None)[1] == ("tj", "86.2 °C", "warn")  # null: the board default again (85/95)
    use_levels(None)  # an older server
    assert cli.LIMITS["memory"] == (10, 20)


def test_fallback_board_levels_match_the_server():
    """The command's copy for older servers is the server's table."""
    from platmon import BOARD_TEMPERATURE
    assert {k: list(v) for k, v in cli.TEMP_LIMITS.items()} == BOARD_TEMPERATURE


def test_data_age_is_the_servers_plus_time_since():
    assert data_age({"sample": {"data_age_ms": 1500}}, got=10.0, now=12.0) == 3.5
    assert data_age({}, got=10.0, now=12.0) == 2.0  # an older server: the time since its answer
    assert data_age({"sample": {"data_age_ms": None}}, got=10.0, now=10.5) == 0.5


def test_busiest_interfaces_first():
    rate = lambda name, rx, tx=0: {"name": name, "rx": {"errors": 0, "dropped": 0}, "tx": {"errors": 0, "dropped": 0},
                                   "rates": {"rx_bytes_per_s": rx, "tx_bytes_per_s": tx,
                                             "rx_packets_per_s": 0, "tx_packets_per_s": 0}}
    items = [rate("br0", 0), {"name": "wlan1", "rates": None, "reason": "warmup"}, rate("eth0", 10, 5), rate("can0", 0)]
    assert [i["name"] for i in busiest_first(items)] == ["eth0", "br0", "can0", "wlan1"]
    narrow = plain(screen(dict(FULL, network={"interfaces": items}), None, 70, 40, Style(), LIVE, {}))
    assert any(line.strip().startswith("eth0") for line in narrow)  # two rows on a narrow screen: the busy one shown


def test_ascii_on_request():
    assert make_style({}, "utf-8").full == "█"
    assert make_style({"PLATMON_ASCII": "1"}, "utf-8").full == "#"
    assert make_style({}, "ascii").full == "#" and make_style({"NO_COLOR": "1"}, "UTF-8").color is False


def test_render_is_unchanged_by_the_live_view():
    """--once, pipes and /text keep the plain screen."""
    assert "\033" not in render(HOT)
