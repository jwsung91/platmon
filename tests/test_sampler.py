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


def test_stale_snapshot_is_not_served():
    """collect keeps failing after one success: the old snapshot counts until stale_after, then None."""
    ok = [True]

    def collect():
        if not ok[0]:
            raise OSError("sensor gone")
        return {"ok": True}

    s = Sampler(collect, interval=0.01, stale_after=0.1).start()
    assert s.latest() == {"ok": True}
    ok[0] = False
    time.sleep(0.2)
    assert s.latest() is None
    ok[0] = True  # recovers as soon as collect works again
    time.sleep(0.05)
    assert s.latest() == {"ok": True}
    s.stop()


def test_default_stale_after():
    assert Sampler(dict, interval=1.0).stale_after == 5.0  # floor, so a slow collect alone does not trip it
    assert Sampler(dict, interval=10.0).stale_after == 30.0
