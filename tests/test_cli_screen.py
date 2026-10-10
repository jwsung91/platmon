"""The live terminal view (screen()): fits the terminal, levels like the web page, plain without color."""
import re
from collections import deque

import pytest

from frontends.cli import ANSI, Style, attention, fit, render, screen, vlen
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


def test_render_is_unchanged_by_the_live_view():
    """--once, pipes and /text keep the plain screen."""
    assert "\033" not in render(HOT)
