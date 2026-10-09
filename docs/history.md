# Recent history (`/api/history`)

With `[history] enabled = yes`, the service keeps the last `retention` seconds (600 by default, 60 to
3600) of selected numbers from its published snapshots, **in memory only** (no file, no database; a
restart starts empty), and serves them at `/api/history` for trend graphs. **Off by default.**

```json
{
  "schema_version": 1,
  "instance_id": "8dfad9fa-9bf0-4d61-91e0-ef22aebd2b91",
  "retention_s": 600.0,
  "interval_ms": 1000.0,
  "dropped_series": 0,
  "series": {
    "memory/used_bytes": [[41, 2000.0, 2147483648], [42, 1000.0, 2147483648]],
    "network/netns1:3f0c…/2/eth0/rx_bytes_per_s": [[41, 2000.0, null], [42, 1000.0, 1024.0]]
  }
}
```

## What is kept

One point per **published** core snapshot, appended by the collector thread when it publishes: a failed
or dropped collection adds nothing, and HTTP requests never add points. A point is
`[sample.sequence, age_ms, value]`: the sequence of the snapshot it comes from and how long ago that
collection started (elapsed clock, as of the answer; wall-clock steps do not change it).

| series id | value | identity |
| --- | --- | --- |
| `cpu/<id>/usage` | CPU usage % | the CPU id |
| `memory/used_bytes` | used memory | - |
| `temperature/<source id>` (or `temperature/name:<key>` without an id) | °C | `sensor_meta` source id ([api.md](api.md#sensor-sources-and-read-times)) |
| `network/<namespace id>/<ifindex>/<name>/rx_bytes_per_s`, `…/tx_bytes_per_s` | bytes/s | namespace, index and name together ([network.md](network.md#scope-and-identity)); interfaces without a known index are not kept |
| `disk_io/<major>:<minor>/<name>/read_bytes_per_s`, `…/write_bytes_per_s` | bytes/s | device number and name ([disk-io.md](disk-io.md)) |

A replaced device, another namespace or index, or a new source id starts a **new** series instead of
continuing an old one. Rates are the server's own, never recomputed from the counters.

Gaps: a value without a rate (`warmup`, `gap`, `counter_regressed`, a CPU without usage) is `null`, never 0
and never interpolated. A series missing from a snapshot gets no point for it: the jump in `sequence` is the
gap. Low-frequency groups (`/api/observations`) are not in the history.

## Bounds

- At most `retention / interval + 2` points per series and 64 series; series beyond that are not kept and
  counted in `dropped_series`. A series not seen for longer than `retention` is removed, so devices that come
  and go do not pile up.
- `/api/history?prefix=…&seconds=…&points=…` (all optional): series whose id starts with `prefix` (at most
  128 characters), from the last `seconds` (up to `retention`), at most `points` per series (1 to 600, default
  300; evenly picked, the newest kept). Anything else is 400. 404 when history is off.
- Reading copies the points out under a short lock and serializes outside it; appending never waits for a
  reader's serialization.

## Web page

With history on, the page shows a "History" panel: a small line per memory, temperature, network and disk
series (at most 12), the latest value next to it, "no value" when the latest point is a gap; a gap breaks the
line. It asks `/api/history?points=120` at most every 10 s while visible and stops after a 404. The
`platmon` command and `/text` do not show history.

## Not included

Persistence across restarts, CPU and low-frequency groups in the graphs, zooming, export, alerts.
