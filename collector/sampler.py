"""The running core: one background thread calls collect() every interval and keeps the latest snapshot,
so every frontend reads the same data without collecting on its own."""
import sys
import threading
import time


class Sampler:
    def __init__(self, collect, interval=1.0):
        self.collect = collect
        self.interval = interval
        self._latest = None
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
                self._latest = self.collect()
                self._ready.set()
            except Exception as e:  # one bad read must not stop the core; frontends keep the last snapshot
                print(f"platmon: collect failed: {e!r}", file=sys.stderr)
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - t0)))

    def latest(self, timeout=5.0):
        """Most recent snapshot; waits up to timeout for the first one. None if there is none yet."""
        self._ready.wait(timeout)
        return self._latest
