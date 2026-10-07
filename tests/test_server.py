import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from frontends.server import make_handler


class FakeSampler:
    interval = 1.0

    def __init__(self, stats):
        self.stats = stats

    def latest(self, timeout=5.0):
        return self.stats


def serve(stats, web=True):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FakeSampler(stats), web))
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


@pytest.mark.parametrize("web, path, expected", [
    (True, "/api/stats", 200), (True, "/text", 200), (True, "/", 200), (True, "/index.html", 200),
    (True, "/nope", 404),
    (False, "/api/stats", 200), (False, "/text", 200), (False, "/", 404),  # web = no: API and text only
    (False, "/index.html", 404),
    (False, "/assets/brand/platmon-logo-light.svg", 404),
    (False, "/assets/brand/platmon-logo-dark.svg", 404),
    (False, "/assets/brand/favicon.svg", 404),
])
def test_routes(web, path, expected):
    from test_cli import FULL
    httpd, base = serve(FULL, web)
    try:
        code, body = status(base + path)
        assert code == expected
        if path == "/api/stats":
            assert json.loads(body) == FULL
        if path == "/text":  # the terminal view, no screen control codes
            assert body.decode().startswith("Test Board\n") and b"\033[" not in body
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("filename", ["platmon-logo-light.svg", "platmon-logo-dark.svg", "favicon.svg"])
def test_brand_assets(filename):
    asset = Path(__file__).resolve().parents[1] / "frontends" / "web" / "assets" / "brand" / filename
    httpd, base = serve(None)
    try:
        with urllib.request.urlopen(base + "/assets/brand/" + filename, timeout=5) as r:
            assert r.status == 200
            assert r.headers["Content-Type"] == "image/svg+xml"
            assert r.read() == asset.read_bytes()
    finally:
        httpd.shutdown()


def test_web_asset_paths_are_allowlisted(tmp_path, monkeypatch):
    brand_dir = tmp_path / "assets" / "brand"
    brand_dir.mkdir(parents=True)
    (brand_dir / "private.svg").write_text("private asset")
    (tmp_path / "index.html").write_text("private page")
    monkeypatch.setattr("frontends.server.WEB_DIR", str(tmp_path))
    httpd, base = serve(None)
    try:
        for path in (
            "/assets/brand/",
            "/assets/brand/private.svg",
            "/assets/brand/../../index.html",
            "/assets/brand/%2e%2e/%2e%2e/index.html",
        ):
            assert status(base + path)[0] == 404, path
    finally:
        httpd.shutdown()


def test_no_snapshot_yet_is_503():
    """JSON for the API and text for /text, so clients need not parse an HTML error page."""
    httpd, base = serve(None)
    try:
        for path, ctype in (("/api/stats", "application/json"), ("/text", "text/plain; charset=utf-8")):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + path, timeout=5)
            assert e.value.code == 503 and e.value.headers["Content-Type"] == ctype
            body = e.value.read().decode()
            assert (json.loads(body)["error"] if path == "/api/stats" else body).startswith("no current data")
    finally:
        httpd.shutdown()
