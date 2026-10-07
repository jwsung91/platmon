"""The web page's script, run in Node against scripted responses (skipped where Node is missing)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_web_survives_errors_and_recovers():
    out = subprocess.run([NODE, str(ROOT / "tests/web_harness.js"), str(ROOT / "frontends/web/index.html")],
                         capture_output=True, text=True, timeout=30, check=True).stdout
    steps = {s["step"]: s for s in map(json.loads, out.splitlines())}
    assert list(steps) == ["ok", "503", "hang", "down", "garbage", "recovered"]

    assert steps["ok"]["err"] == ""
    assert steps["503"]["err"] == ("No current data: platmon is running but has no recent sample (see its log)"
                                   " · showing data from 1 s ago")
    assert steps["hang"]["err"] == "No answer within 5 s · showing data from 7 s ago"  # timed out, not stuck
    assert steps["down"]["err"] == "Connection lost: Failed to fetch · showing data from 8 s ago"
    assert steps["garbage"]["err"] == "Unexpected response (not platmon data) · showing data from 9 s ago"
    assert steps["recovered"]["err"] == ""
    for s in steps.values():
        assert s["shows_data"], s            # the last good values stay on screen
        assert s["refresh_scheduled"] == 1, s  # exactly one next update, whatever happened
