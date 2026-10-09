from pathlib import Path

import pytest

from platmon import load_config

SHIPPED_INI = str(Path(__file__).parent.parent / "platmon.ini")


def enabled(cfg):
    return {name for name in ("http",) if cfg[name].getboolean("enabled")}


def test_defaults():
    cfg = load_config()
    assert enabled(cfg) == {"http"}
    assert cfg["http"].getint("port") == 9797 and cfg["http"].getboolean("web")
    assert cfg["core"].getfloat("interval") == 1.0


def test_shipped_ini_matches_defaults():
    assert {s: dict(load_config(SHIPPED_INI)[s]) for s in ("core", "network", "http")} == \
           {s: dict(load_config()[s]) for s in ("core", "network", "http")}


def test_file_overrides_defaults(tmp_path):
    ini = tmp_path / "p.ini"
    ini.write_text("[http]\nport = 9000\nweb = no\n")
    cfg = load_config(str(ini))
    assert cfg["http"].getint("port") == 9000 and not cfg["http"].getboolean("web")
    assert cfg["http"]["bind"] == "0.0.0.0"  # untouched keys keep their default
    assert enabled(cfg) == {"http"}


def test_frontends_flag_enables_exactly_those(tmp_path):
    ini = tmp_path / "p.ini"
    ini.write_text("[http]\nenabled = no\n")
    assert enabled(load_config(str(ini), ["http"])) == {"http"}


@pytest.mark.parametrize("ini, frontends, error", [
    ("[htpp]\nport = 1\n", None, "unknown config section"),  # typos must not be silently ignored
    ("[http]\nprot = 9000\n", None, r"\[http\] unknown key\(s\): prot"),
    ("", ["web"], "unknown frontend"),
    ("", ["terminal"], "unknown frontend"),
    # configs from before the terminal view moved to the platmon command say what to do
    ("[terminal]\nenabled = no\n", None, r"\[terminal\] is no longer supported: .*platmon. command"),
    # bad values end in one clear error, not a traceback from deep inside a frontend
    ("[http]\nport = abc\n", None, r"port = 'abc' is not a valid int"),
    ("[http]\nenabled = maybe\n", None, "is not a valid bool"),
    ("[http]\nport = 70000\n", None, "out of range"),
    ("[core]\ninterval = 0\n", None, "out of range"),  # 0 would make the sampler spin
    # loads fine but would start nothing: refused here, so install.sh refuses before replacing anything
    ("[http]\nenabled = no\n", None, r"nothing to run: every output is disabled; set enabled = yes in \[http\]"),
    ("", [], "nothing to run"),  # --frontends with no name
    ("[core]\ninterval = -1\n", None, "out of range"),
    ("port = 1\n", None, "cannot parse config"),  # no section header
    ("[http]\nbind = 10%\n", ["http"], None),  # % is literal, not interpolation
])
def test_rejects_bad_config(tmp_path, ini, frontends, error):
    path = tmp_path / "p.ini"
    path.write_text(ini)
    if error is None:
        load_config(str(path), frontends)
        return
    with pytest.raises(ValueError, match=error):
        load_config(str(path), frontends)


def test_missing_file():
    with pytest.raises(ValueError, match="cannot read"):
        load_config("/nonexistent/platmon.ini")


def test_sigterm_exits_promptly(tmp_path):
    """docker/systemd stop sends SIGTERM; platmon must exit right away with status 0."""
    import os
    import signal
    import socket
    import subprocess
    import sys
    import time

    with socket.socket() as s:  # a free port for the http frontend
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    ini = tmp_path / "p.ini"
    ini.write_text(f"[http]\nbind = 127.0.0.1\nport = {port}\n")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = subprocess.Popen([sys.executable, os.path.join(root, "platmon.py"), str(ini)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert "platmon: platform" in p.stdout.readline()  # started, startup line logged
    time.sleep(0.3)
    p.send_signal(signal.SIGTERM)
    t0 = time.monotonic()
    assert p.wait(timeout=5) == 0
    assert time.monotonic() - t0 < 2
