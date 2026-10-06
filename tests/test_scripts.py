import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).parent.parent / "scripts").glob("*/*.sh"))


def test_expected_scripts_exist():
    assert [f"{p.parent.name}/{p.name}" for p in SCRIPTS] == \
           ["docker/start.sh", "docker/stop.sh",
            "systemd/install.sh", "systemd/start.sh", "systemd/stop.sh", "systemd/uninstall.sh"]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_script_is_executable_bash(script):
    assert os.access(script, os.X_OK)
    subprocess.run(["bash", "-n", str(script)], check=True)  # syntax only; they need sudo/docker to run
