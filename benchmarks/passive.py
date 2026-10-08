"""Bench-only prototype of passive Network / Disk / PSI collection, for benchmarks/cadence.py. Not a product
API: the output goes into the bench response as "_bench_passive" only.

Each callback reads /proc/net/dev, /proc/diskstats and the PSI files once each and turns two consecutive
readings into rates over the time actually observed between them (not the configured interval). A row
without a usable previous reading (first sight, counter went backwards) has rate None and a reason, never 0.
"""
import errno
import os
import time

PSI = ("cpu", "memory", "io")
SKIP_DISKS = ("loop", "ram")  # ponytail: virtual block devices by name; a real allowlist when this becomes product code


def parse_net_dev(text):
    """{iface: (rx_bytes, rx_packets, tx_bytes, tx_packets)} from /proc/net/dev."""
    out = {}
    for line in text.splitlines()[2:]:
        name, sep, rest = line.partition(":")
        f = rest.split()
        if sep and len(f) >= 16:
            out[name.strip()] = (int(f[0]), int(f[1]), int(f[8]), int(f[9]))
    return out


def parse_diskstats(text):
    """{dev: (reads, sectors_read, writes, sectors_written, io_ticks_ms)} from /proc/diskstats."""
    out = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 14:
            out[f[2]] = (int(f[3]), int(f[5]), int(f[7]), int(f[9]), int(f[12]))
    return out


def parse_psi(text):
    """{"some"|"full": {"avg10": float, "total_us": int}} from one /proc/pressure file."""
    out = {}
    for line in text.splitlines():
        kind, *fields = line.split()
        kv = dict(x.split("=", 1) for x in fields)
        out[kind] = {"avg10": float(kv["avg10"]), "total_us": int(kv["total"])}
    return out


class Passive:
    def __init__(self, proc="/proc", sys="/sys", clock=time.monotonic_ns):
        self.proc, self.sys, self.clock = proc, sys, clock
        self.prev = {}        # source -> (elapsed ns at the read, parsed)
        self.physical = {}    # iface -> bool, looked up once per new iface
        self.whole_disk = {}  # dev -> bool, looked up once per new device
        self.reads = self.read_bytes = self.lookups = 0

    def _read(self, path):
        with open(path, "rb") as f:
            data = f.read()
        self.reads += 1
        self.read_bytes += len(data)
        return data.decode()

    def _rates(self, source, now, cur):
        """{key: (row, deltas or None, seconds or None, reason or None)} against the previous reading."""
        last = self.prev.get(source)
        self.prev[source] = (now, cur)
        out = {}
        for key, row in cur.items():
            old = last and last[1].get(key)
            if old is None:
                out[key] = (row, None, None, "warmup")
            elif any(a < b for a, b in zip(row, old)):
                out[key] = (row, None, None, "counter_reset")
            elif now <= last[0]:
                out[key] = (row, None, None, "invalid_interval")
            else:
                out[key] = (row, [a - b for a, b in zip(row, old)], (now - last[0]) / 1e9, None)
        gone = sorted(set(last[1]) - set(cur)) if last else []
        return out, gone

    def _guarded(self, fn):
        try:
            return fn()
        except OSError as e:
            unsupported = e.errno in (errno.ENOENT, errno.EOPNOTSUPP)
            return {"state": "unsupported" if unsupported else "error", "reason": errno.errorcode.get(e.errno, str(e))}

    def network(self):
        now = self.clock()
        rows, gone = self._rates("net", now, parse_net_dev(self._read(f"{self.proc}/net/dev")))
        out = {}
        for name, (row, d, s, why) in rows.items():
            if name not in self.physical:
                self.lookups += 1
                self.physical[name] = os.path.exists(f"{self.sys}/class/net/{name}/device")
            r = {"physical": self.physical[name], "rx_bytes": row[0], "tx_bytes": row[2], "reason": why}
            if d:
                r.update(rx_bytes_per_s=d[0] / s, tx_bytes_per_s=d[2] / s, rx_bits_per_s=8 * d[0] / s,
                         tx_bits_per_s=8 * d[2] / s, window_s=s)
            out[name] = r
        return {"state": "ok", "interfaces": out, "removed": gone}

    def disk(self):
        now = self.clock()
        stats = parse_diskstats(self._read(f"{self.proc}/diskstats"))
        for dev in stats.keys() - self.whole_disk.keys():  # partitions have no /sys/block entry: never summed
            self.lookups += 1
            self.whole_disk[dev] = not dev.startswith(SKIP_DISKS) and os.path.exists(f"{self.sys}/block/{dev}")
        rows, gone = self._rates("disk", now, {k: v for k, v in stats.items() if self.whole_disk[k]})
        out = {}
        for dev, (row, d, s, why) in rows.items():
            r = {"reads": row[0], "writes": row[2], "reason": why}
            if d:  # io_time_ratio: share of the window with I/O in flight, not device saturation
                r.update(read_bytes_per_s=512 * d[1] / s, write_bytes_per_s=512 * d[3] / s,
                         reads_per_s=d[0] / s, writes_per_s=d[2] / s, io_time_ratio=min(1.0, d[4] / 1000 / s),
                         window_s=s)
            out[dev] = r
        return {"state": "ok", "devices": out, "removed": gone}

    def pressure(self, name):
        now = self.clock()
        parsed = parse_psi(self._read(f"{self.proc}/pressure/{name}"))
        rows, _ = self._rates(f"psi.{name}", now, {k: (v["total_us"],) for k, v in parsed.items()})
        out = {"state": "ok"}
        for kind, (row, d, s, why) in rows.items():
            out[kind] = {"avg10": parsed[kind]["avg10"], "total_us": row[0], "reason": why,
                         "stall_ratio": d[0] / 1e6 / s if d else None}
        return out

    def __call__(self):
        return {"network": self._guarded(self.network), "disk": self._guarded(self.disk),
                "pressure": {n: self._guarded(lambda n=n: self.pressure(n)) for n in PSI}}
