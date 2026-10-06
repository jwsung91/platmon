from pathlib import Path

import pytest

from platmon import load_config

SHIPPED_INI = str(Path(__file__).parent.parent / "platmon.ini")


def enabled(cfg):
    return {name for name in ("http", "terminal") if cfg[name].getboolean("enabled")}


def test_defaults():
    cfg = load_config()
    assert enabled(cfg) == {"http"}
    assert cfg["http"].getint("port") == 8080 and cfg["http"].getboolean("web")
    assert cfg["core"].getfloat("interval") == 1.0


def test_shipped_ini_matches_defaults():
    assert {s: dict(load_config(SHIPPED_INI)[s]) for s in ("core", "http", "terminal")} == \
           {s: dict(load_config()[s]) for s in ("core", "http", "terminal")}


def test_file_overrides_defaults(tmp_path):
    ini = tmp_path / "p.ini"
    ini.write_text("[http]\nport = 9000\nweb = no\n[terminal]\nenabled = yes\n")
    cfg = load_config(str(ini))
    assert cfg["http"].getint("port") == 9000 and not cfg["http"].getboolean("web")
    assert cfg["http"]["bind"] == "0.0.0.0"  # untouched keys keep their default
    assert enabled(cfg) == {"http", "terminal"}


def test_frontends_flag_enables_exactly_those(tmp_path):
    ini = tmp_path / "p.ini"
    ini.write_text("[http]\nenabled = yes\n")
    assert enabled(load_config(str(ini), ["terminal"])) == {"terminal"}


@pytest.mark.parametrize("ini, frontends, error", [
    ("[htpp]\nport = 1\n", None, "unknown config section"),  # typo must not be silently ignored
    ("", ["web"], "unknown frontend"),
])
def test_rejects_unknown(tmp_path, ini, frontends, error):
    path = tmp_path / "p.ini"
    path.write_text(ini)
    with pytest.raises(ValueError, match=error):
        load_config(str(path), frontends)


def test_missing_file():
    with pytest.raises(ValueError, match="cannot read"):
        load_config("/nonexistent/platmon.ini")
