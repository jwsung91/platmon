"""The running core: one background thread calls collect() every interval and keeps the latest snapshot,
so every frontend reads the same data without collecting on its own.

Each published snapshot carries sample metadata (instance_id, sequence, start/end times) and the sampler
tracks the latest attempt, so readers can tell a repeated read of the same sample from a new one, and a
fresh sample from the last good one while collection fails. See docs/api.md.
"""
import copy
import sys
import threading
import time
import uuid

SCHEMA_VERSION = 1
METADATA_KEYS = ("schema_version", "sample", "collectors")  # added to the stats dict by read()


def pick_clock():
    """Elapsed-time clock for durations and freshness, chosen once: CLOCK_BOOTTIME keeps counting through
    suspend (Linux); monotonic is the fallback. Returns (nanoseconds function, description)."""
    try:
        boottime = time.CLOCK_BOOTTIME
        time.clock_gettime_ns(boottime)
    except (AttributeError, OSError):
        return time.monotonic_ns, {"source": "monotonic", "suspend_aware": False}
    return (lambda: time.clock_gettime_ns(boottime)), {"source": "boottime", "suspend_aware": True}


def ms(ns):
    return round(ns / 1e6, 3)


class Sampler:
    def __init__(self, collect, interval=1.0, stale_after=None, clock=None, wall=time.time):
        """stale_after: seconds after which the last good snapshot no longer counts as current
        (default: 3 intervals, at least 5 s, so a slow collect alone does not trip it).
        clock: (elapsed nanoseconds function, description) as from pick_clock(); wall: Unix seconds.
        Both are injectable for tests."""
        self.collect = collect
        self.interval = interval
        self.stale_after = stale_after if stale_after is not None else max(3 * interval, 5.0)
        self._stale_ns = round(self.stale_after * 1e9)
        self._elapsed, self.clock = clock or pick_clock()
        self._wall = wall
        self.instance_id = str(uuid.uuid4())
        # state below changes only under _lock, and only by the one writer thread (or a test calling _attempt)
        self._lock = threading.Lock()
        self._record = None        # last published snapshot: stats + sample metadata, never modified after
        self._attempt_result = None  # latest completed attempt
        self._collecting_since = None  # elapsed ns the running attempt started, None between attempts
        self._sequence = 0
        self._failures = 0
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        """Starts the one writer thread; again while running does nothing. A stopped sampler cannot restart:
        make a new one."""
        if self._stop.is_set():
            raise RuntimeError("sampler was stopped; create a new Sampler instead of restarting it")
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="sampler", daemon=True)
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            started = self._attempt()
            self._stop.wait(max(0.0, self.interval - (self._elapsed() - started) / 1e9))

    def _attempt(self):
        """One collection: run collect() without the lock, then publish the result as one consistent update.
        Returns the elapsed ns it started."""
        started_at, started = self._wall(), self._elapsed()
        with self._lock:
            self._collecting_since = started
        reason = None
        try:
            stats = copy.deepcopy(self.collect())
        except Exception as e:  # one bad read must not stop the core; the last snapshot serves until stale
            print(f"platmon: collect failed: {e!r}", file=sys.stderr)
            reason = "collection_failed"
        completed_at, completed = self._wall(), self._elapsed()
        duration = completed - started
        if reason is None and duration > self._stale_ns:  # already stale on arrival: not new data
            print(f"platmon: collect took {duration / 1e9:.1f} s, longer than stale_after "
                  f"({self.stale_after:g} s); result dropped", file=sys.stderr)
            reason = "collection_too_slow"
        with self._lock:
            self._collecting_since = None
            self._failures = 0 if reason is None else self._failures + 1
            self._attempt_result = {"state": "error" if reason else "ok", "reason": reason,
                                    "completed_at": completed_at, "duration_ns": duration,
                                    "consecutive_failures": self._failures}
            if reason is None:
                self._sequence += 1
                self._record = {"stats": stats, "sequence": self._sequence, "started_at": started_at,
                                "completed_at": completed_at, "started": started, "completed": completed}
                self._ready.set()
        return started

    def read(self, timeout=0.0):
        """(stats, status) from one capture of the state, so both describe the same moment.
        stats: the current snapshot with schema_version, sample and collectors added, or None if there is
        none yet or it is stale; waits up to timeout for the first one. status: the /api/status body.
        Both are new dicts: callers may change them."""
        if timeout:
            self._ready.wait(timeout)
        with self._lock:
            now = self._elapsed()
            record, attempt, since = self._record, self._attempt_result, self._collecting_since
        fresh = record is not None and now - record["started"] <= self._stale_ns
        if fresh:
            state = "degraded" if attempt["state"] == "error" else "ready"
        elif record is None and attempt is None and (since is None or now - since <= self._stale_ns):
            state = "starting"
        else:
            state = "stale"
        status = {
            "schema_version": SCHEMA_VERSION, "instance_id": self.instance_id, "state": state, "ready": fresh,
            "sample": record and {"sequence": record["sequence"], "age_ms": ms(now - record["completed"]),
                                  "data_age_ms": ms(now - record["started"])},
            "last_attempt": attempt and {"state": attempt["state"], "reason": attempt["reason"],
                                         "completed_at": attempt["completed_at"],
                                         "duration_ms": ms(attempt["duration_ns"]),
                                         "consecutive_failures": attempt["consecutive_failures"]},
            "collecting_for_ms": None if since is None else ms(now - since),
            "clock": dict(self.clock),
        }
        if not fresh:
            return None, status
        stats = copy.deepcopy(record["stats"])
        stats.update({
            "schema_version": SCHEMA_VERSION,
            "sample": {"instance_id": self.instance_id, "sequence": record["sequence"],
                       "started_at": record["started_at"], "completed_at": record["completed_at"],
                       "duration_ms": ms(record["completed"] - record["started"]),
                       "age_ms": ms(now - record["completed"]), "data_age_ms": ms(now - record["started"]),
                       "data_age_basis": "cycle_start_upper_bound",
                       "interval_ms": ms(round(self.interval * 1e9)), "stale_after_ms": ms(self._stale_ns)},
            # this snapshot's own state when it was made; later failures show in status, not here
            "collectors": {"core": {"state": "ok", "reason": None}},
        })
        return stats, status

    def latest(self, timeout=5.0):
        """Most recent snapshot as collect() returned it (no metadata); waits up to timeout for the first one.
        None if there is none yet or collect has kept failing for longer than stale_after."""
        stats = self.read(timeout)[0]
        return stats and {k: v for k, v in stats.items() if k not in METADATA_KEYS}
