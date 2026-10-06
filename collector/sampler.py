"""The running core: one background thread calls collect() every interval and keeps the latest snapshot,
so every frontend reads the same data without collecting on its own."""
import sys
import threading
import time


class Sampler:
    def __init__(self, collect, interval=1.0, stale_after=None):
        """stale_after: seconds after which the last good snapshot no longer counts as current
        (default: 3 intervals, at least 5 s, so a slow collect alone does not trip it)."""
        self.collect = collect
        self.interval = interval
        self.stale_after = stale_after if stale_after is not None else max(3 * interval, 5.0)
        self._snapshot = None  # (monotonic time it was collected, stats), replaced as one object
        self._ready = threading.Event()
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name="sampler", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                self._snapshot = (time.monotonic(), self.collect())
                self._ready.set()
            except Exception as e:  # one bad read must not stop the core; the last snapshot serves until stale
                print(f"platmon: collect failed: {e!r}", file=sys.stderr)
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - t0)))

    def latest(self, timeout=5.0):
        """Most recent snapshot; waits up to timeout for the first one.
        None if there is none yet or collect has kept failing for longer than stale_after."""
        self._ready.wait(timeout)
        snapshot = self._snapshot
        if snapshot is None or time.monotonic() - snapshot[0] > self.stale_after:
            return None
        return snapshot[1]
