"""Recent history: the last few minutes of selected numbers from the published core snapshots, in memory
only (no file, no database), for trend graphs. One point per published snapshot, appended by the Sampler's
writer thread; reading never adds points. Contract: docs/history.md.
"""
import collections
import threading

from .sysfs import pointer

MAX_SERIES = 64


def points_of(stats, sensor_meta):
    """{series id: value or None} for one snapshot. Ids follow the identities the API already gives, so a
    replaced device, another namespace or a renamed sensor starts a new series instead of continuing one.
    A value without a rate (warmup, gap, counter went down) is None: a gap, never 0."""
    out = {}
    for c in stats.get("cpu") or []:
        out[f"cpu/{c['id']}/usage"] = c.get("usage")
    m = stats.get("memory") or {}
    if "used" in m:
        out["memory/used_bytes"] = m["used"]
    meta = sensor_meta or {}
    for key, value in (stats.get("temperature") or {}).items():
        sid = (meta.get(pointer("temperature", key)) or {}).get("id")
        out[f"temperature/{sid or 'name:' + key}"] = value
    net = stats.get("network") or {}
    ns = (net.get("scope") or {}).get("id")
    for i in net.get("interfaces") or []:
        if ns is None or i.get("ifindex") is None:
            continue  # no identity to tie points of one interface together
        for k in ("rx_bytes_per_s", "tx_bytes_per_s"):
            out[f"network/{ns}/{i['ifindex']}/{i['name']}/{k}"] = (i.get("rates") or {}).get(k)
    for d in (stats.get("disk_io") or {}).get("disks") or []:
        for k in ("read_bytes_per_s", "write_bytes_per_s"):
            out[f"disk_io/{d['major']}:{d['minor']}/{d['name']}/{k}"] = (d.get("rates") or {}).get(k)
    return out


class History:
    """retention: seconds kept; interval: the collection interval, for the point limit per series."""

    def __init__(self, retention, interval, max_series=MAX_SERIES):
        self.retention, self._retention_ns = retention, round(retention * 1e9)
        self._maxlen = int(retention / interval) + 2
        self._max_series = max_series
        self._lock = threading.Lock()
        self._series = {}       # id -> deque of (sequence, elapsed ns of the snapshot's start, value)
        self.dropped_series = 0  # new series not kept because max_series were already there

    def append(self, record):
        """One published Sampler record (never changed, only read here)."""
        values = points_of(record["stats"], record.get("sensor_meta"))
        point = (record["sequence"], record["started"])
        with self._lock:
            for sid, value in values.items():
                series = self._series.get(sid)
                if series is None:
                    if len(self._series) >= self._max_series:
                        self.dropped_series += 1
                        continue
                    series = self._series[sid] = collections.deque(maxlen=self._maxlen)
                series.append((*point, value))
            cutoff = record["started"] - self._retention_ns  # series not seen within the retention go away
            for sid in [s for s, d in self._series.items() if d[-1][1] < cutoff]:
                del self._series[sid]

    def view(self, now, prefix="", seconds=None, points=300):
        """{series id: [[sequence, age_ms, value], ...]} of the series starting with prefix, at most
        `points` per series (evenly picked, newest kept) from the last `seconds`. A copy: safe to
        serialize without the lock."""
        seconds = self.retention if seconds is None else min(seconds, self.retention)
        since = now - round(seconds * 1e9)
        with self._lock:
            picked = {sid: [p for p in d if p[1] >= since] for sid, d in self._series.items() if sid.startswith(prefix)}
            dropped = self.dropped_series
        out = {}
        for sid, ps in picked.items():
            step = max(1, -(-len(ps) // points))
            ps = ps[::-1][::step][::-1]  # every step-th point, counted from the newest
            out[sid] = [[seq, round((now - t) / 1e6, 3), v] for seq, t, v in ps]
        return out, dropped
