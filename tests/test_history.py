"""collector/history.py and /api/history: which numbers are kept under which identity, gaps, bounds,
retention, and that only published snapshots append. Fake clocks; no host data."""
import json
import threading

import pytest

from collector.history import History, points_of
from collector.sampler import Sampler
from frontends.server import make_handler
from test_sampler import Clock, fake
from test_server import get

S = 10**9


def stats(n, rx=100.0, ns="netns1:a", ifindex=2, disk_rates=True):
    return {"cpu": [{"id": 0, "usage": 10.0 + n}, {"id": 1, "usage": None}], "memory": {"used": 1000 + n},
            "temperature": {"cpu": 40.0, "a/b": 41.0},
            "network": {"scope": {"id": ns}, "interfaces": [
                {"name": "eth0", "ifindex": ifindex, "rates": {"rx_bytes_per_s": rx, "tx_bytes_per_s": 0.0}},
                {"name": "wlan0", "ifindex": 3, "rates": None, "reason": "warmup"},
                {"name": "odd", "ifindex": None, "rates": {"rx_bytes_per_s": 1.0, "tx_bytes_per_s": 1.0}}]},
            "disk_io": {"disks": [{"name": "sda", "major": 8, "minor": 0,
                                   "rates": {"read_bytes_per_s": 5.0, "write_bytes_per_s": 6.0} if disk_rates else None}]}}


def test_series_ids_follow_identities_and_gaps_are_none():
    meta = {"/temperature/cpu": {"id": "src1:abc"}, "/temperature/a~1b": {"id": None}}
    p = points_of(stats(1), meta)
    assert p["cpu/0/usage"] == 11.0 and p["cpu/1/usage"] is None
    assert p["memory/used_bytes"] == 1001
    assert p["temperature/src1:abc"] == 40.0 and p["temperature/name:a/b"] == 41.0  # no id: by name, marked so
    assert p["network/netns1:a/2/eth0/rx_bytes_per_s"] == 100.0
    assert p["network/netns1:a/3/wlan0/rx_bytes_per_s"] is None  # warmup: a gap, not 0
    assert not any("/odd/" in k for k in p)  # no ifindex: no identity to join points on
    assert p["disk_io/8:0/sda/read_bytes_per_s"] == 5.0
    assert points_of(stats(1, disk_rates=False), {})["disk_io/8:0/sda/write_bytes_per_s"] is None


def test_a_new_namespace_or_index_is_a_new_series():
    a, b = points_of(stats(1), {}), points_of(stats(1, ns="netns1:b", ifindex=9), {})
    assert not {k for k in a if k.startswith("network/")} & {k for k in b if k.startswith("network/")}


def record(n, t):
    return {"stats": stats(n), "sensor_meta": {}, "sequence": n, "started": t}


def test_points_are_bounded_and_old_series_go_away():
    h = History(retention=60, interval=1.0, max_series=64)
    for n in range(1, 500):
        h.append(record(n, n * S))
    series, dropped = h.view(499 * S)
    assert len(h._series["memory/used_bytes"]) == 62  # memory: retention / interval + 2 points at most
    assert len(series["memory/used_bytes"]) == 61 and series["memory/used_bytes"][-1] == [499, 0.0, 1499]  # last 60 s
    later = {"stats": {"memory": {"used": 1}}, "sensor_meta": {}, "sequence": 550, "started": 550 * S}
    h.append(later)  # eth0, sda and the CPUs are not in it: kept until they are older than the retention
    assert "cpu/0/usage" in h.view(550 * S)[0]
    h.append({**later, "sequence": 700, "started": 700 * S})
    assert list(h.view(700 * S)[0]) == ["memory/used_bytes"]


def test_series_limit_counts_what_it_drops():
    h = History(retention=60, interval=1.0, max_series=3)
    h.append(record(1, S))
    series, dropped = h.view(S)
    assert len(series) == 3 and dropped == len(points_of(stats(1), {})) - 3


def test_view_bounds_prefix_seconds_and_points():
    h = History(retention=600, interval=1.0)
    for n in range(1, 301):
        h.append(record(n, n * S))
    s, _ = h.view(300 * S, prefix="memory/", seconds=100, points=10)
    pts = s["memory/used_bytes"]
    assert list(s) == ["memory/used_bytes"] and len(pts) == 10 and pts[-1][0] == 300  # newest kept
    assert all(p[1] <= 100000.0 for p in pts)
    s, _ = h.view(300 * S, seconds=10**6)  # capped at the retention
    assert len(s["memory/used_bytes"]) == 300


def test_only_published_snapshots_append_and_reads_never_do():
    c = Clock()
    seq = [0]

    def collect():
        seq[0] += 1
        if seq[0] == 2:
            raise OSError("required read failed")
        if seq[0] == 3:
            c.advance(10)  # too slow: dropped
        return stats(seq[0])
    s = fake(collect, c)
    h = History(retention=600, interval=1.0)
    s.on_publish = h.append
    for _ in range(4):
        c.advance(1)
        s._attempt()
    for _ in range(20):
        s.read()
        s._stats_json()
    assert [p[0] for p in h.view(c.ns)[0]["memory/used_bytes"]] == [1, 2]  # sequences 1 and 2: attempts 1 and 4


def test_a_failing_append_never_stops_the_core(capsys):
    c = Clock()
    s = fake(lambda: {"v": 1}, c)
    s.on_publish = lambda record: 1 / 0
    s._attempt()
    assert s.read()[0]["sample"]["sequence"] == 1 and "history append failed" in capsys.readouterr().err


def test_concurrent_append_and_view():
    h = History(retention=60, interval=1.0)
    done = threading.Event()
    errors = []

    def reader():
        while not done.is_set():
            try:
                json.dumps(h.view(10**12))
            except Exception as e:
                errors.append(e)
    t = threading.Thread(target=reader)
    t.start()
    for n in range(1, 2000):
        h.append(record(n, n * S))
    done.set()
    t.join()
    assert errors == []


@pytest.fixture
def server():
    from http.server import ThreadingHTTPServer
    c = Clock()
    s = Sampler(lambda: stats(1), clock=(lambda: c.ns, {"source": "fake"}), wall=lambda: c.wall)
    h = History(retention=600, interval=1.0)
    s.on_publish = h.append
    s._attempt()
    servers = []

    def start(history):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(s, True, None, history))
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"
    yield start, h
    for httpd in servers:
        httpd.shutdown()


def test_history_endpoint(server):
    start, h = server
    url = start(h)
    code, headers, body = get(url + "/api/history?prefix=memory/&points=5")
    doc = json.loads(body)
    assert (code, headers["Content-Type"], headers["Cache-Control"]) == (200, "application/json", "no-store")
    assert list(doc["series"]) == ["memory/used_bytes"] and doc["retention_s"] == 600 and doc["interval_ms"] == 1000
    for q in ("points=0", "points=601", "seconds=0", "seconds=601", "prefix=" + "x" * 129, "points=x"):
        assert get(url + "/api/history?" + q)[0] == 400, q
    assert get(start(None) + "/api/history")[0] == 404  # history off
