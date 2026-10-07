import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

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
    (True, "/api/stats", 200), (True, "/text", 200), (True, "/", 200), (True, "/nope", 404),
    (False, "/api/stats", 200), (False, "/text", 200), (False, "/", 404),  # web = no: API and text only
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


def test_no_snapshot_yet_is_503():
    httpd, base = serve(None)
    try:
        assert status(base + "/api/stats")[0] == 503
        assert status(base + "/text")[0] == 503
    finally:
        httpd.shutdown()
