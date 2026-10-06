import itertools
import time

from collector.sampler import Sampler


def test_latest_follows_collect():
    n = itertools.count()
    s = Sampler(lambda: {"n": next(n)}, interval=0.01).start()
    first = s.latest()["n"]
    for _ in range(100):
        if s.latest()["n"] > first:
            break
        time.sleep(0.01)
    assert s.latest()["n"] > first
    s.stop()


def test_failed_collect_keeps_last_snapshot():
    calls = itertools.count()

    def collect():
        if next(calls) > 0:
            raise OSError("sensor gone")
        return {"ok": True}

    s = Sampler(collect, interval=0.01).start()
    assert s.latest() == {"ok": True}
    time.sleep(0.05)  # several failing rounds
    assert s.latest() == {"ok": True}
    s.stop()


def test_no_snapshot_yet():
    def collect():
        raise OSError("never works")

    s = Sampler(collect, interval=0.01).start()
    assert s.latest(timeout=0.05) is None
    s.stop()
