# HTTP API

platmon answers on port 9797 (`[http]` in `platmon.ini`). There is no authentication: run it on trusted
networks only. Every answer of `/api/stats`, `/api/status` and `/text` carries `Cache-Control: no-store`.

| Path | Answer |
| --- | --- |
| `/api/stats` | the current snapshot as JSON; 503 when there is none |
| `/api/status` | the collector's runtime status as JSON; always 200, also without the web page |
| `/text` | the `platmon` terminal screen as plain text; 503 when there is no current snapshot |
| `/` | the web page (only with `web = yes`) |

One background thread collects a snapshot every `interval`; HTTP requests only read the latest one and
never collect on their own. `/api/stats` and `/text` wait up to 5 s for the first snapshot after the
service starts; `/api/status` never waits.

## `/api/stats`

The metrics (`cpu`, `gpu`, `memory`, `disk`, `temperature`, `power`, `fans`, `time`, ...) keep their
keys, units and types. Schema version 1 adds three keys next to them; answers without `schema_version`
come from an older platmon (legacy) and have no sample metadata.

```json
{
  "schema_version": 1,
  "sample": {
    "instance_id": "8dfad9fa-9bf0-4d61-91e0-ef22aebd2b91",
    "sequence": 42,
    "started_at": 1791345600.0,
    "completed_at": 1791345600.25,
    "duration_ms": 250.0,
    "age_ms": 100.0,
    "data_age_ms": 350.0,
    "data_age_basis": "cycle_start_upper_bound",
    "interval_ms": 1000.0,
    "stale_after_ms": 5000.0
  },
  "collectors": {"core": {"state": "ok", "reason": null}}
}
```

- `instance_id`, `sequence`: identify the sample. `instance_id` is a random UUID made when the service
  starts (not derived from the host or user); `sequence` counts the snapshots that instance published,
  from 1. Polling does not change them: the same `(instance_id, sequence)` is the same sample read again.
  A failed or dropped collection does not count. After a restart `instance_id` changes and `sequence`
  starts over.
- `started_at`, `completed_at`: wall-clock Unix seconds when the collection began and ended. Shown for
  people; if the system clock is stepped they can be off, even `completed_at < started_at`.
- `duration_ms`, `age_ms`, `data_age_ms`: measured on an elapsed clock (see Clock), not the wall clock.
  `duration_ms` is how long the collection took, `age_ms` the time since it completed and `data_age_ms`
  the time since it started, both as of this answer: `data_age_ms = age_ms + duration_ms` (up to rounding).
- `data_age_basis`: always `cycle_start_upper_bound`. platmon does not know when each value inside a
  collection was read, so it uses the start of the collection: the readings taken in this collection are
  at most this old. CPU usage is an average that reaches back further, to the previous reading (see
  CPU usage); its window is not part of this age.
- `interval_ms`: the configured collection interval. It is not the window CPU usage is averaged over:
  that is `cpu_sampling.window_ms`.
- `stale_after_ms`: when the snapshot stops counting as current: 3 intervals, at least 5 s.
- `collectors.core`: the state when this snapshot was made. `ok` means the collection call succeeded, not
  that every sensor could be read; a missing sensor is still `null` in its field as before, and some or
  all CPUs can still be missing from `cpu` (see `cpu_sampling`). A later failure does not change it: see
  `/api/status`.

A snapshot is current while `data_age_ms <= stale_after_ms`. A collection that already took longer than
`stale_after` is dropped (`collection_too_slow`) instead of being served as new data.

### CPU usage

`cpu` is a list of `{"id", "usage", "freq"}` as before; `usage` is the busy share of the CPU's ticks
between two `/proc/stat` readings (idle and iowait count as idle; guest time is not counted twice), in
percent with one decimal. Next to it, `cpu_sampling` says what that window was:

```json
{
  "cpu": [{"id": 0, "usage": 50.0, "freq": 1200000000}],
  "cpu_sampling": {
    "mode": "interval",
    "window_ms": 1250.0,
    "unavailable": [{"id": 2, "reason": "warmup"}]
  }
}
```

- `mode`: `interval` for the service. It reads `/proc/stat` once per collection and compares with its
  previous successful reading, so a collection no longer waits 250 ms for a second one. `oneshot` for a
  direct `collector.collect()` call without the service's state: two readings 250 ms apart, nothing kept.
- `window_ms`: the elapsed time between the two readings, measured when each reading began. It follows
  the real timing, so it is not `interval_ms` (a collection takes time, and failed ones still read). `null`
  when there is no earlier reading or the clock did not move forward.
- `unavailable`: CPUs that were read but have no `usage` in this sample, with a reason. They are left out
  of `cpu` rather than shown as 0 %; a measured idle CPU is `0.0` and is not listed here.

| Reason | Meaning | Next reading |
| --- | --- | --- |
| `warmup` | no earlier reading of this CPU: the service's first sample, a CPU that came online, or one back after going offline | measured |
| `counter_regressed` | one of its counters went down (iowait can, on some kernels); not treated as a reboot and not clamped | measured, from this reading |
| `no_ticks` | its counters did not move: nothing to average, which is not 0 % | measured, from this reading |
| `invalid_interval` | the elapsed clock did not advance between the readings (all CPUs) | measured, from this reading |
| `gap` | the readings are more than `max(3 × interval, 5 s)` apart (all CPUs), e.g. after failing or slow collections | measured, from this reading |

What changed: until this version, every snapshot's CPU usage covered 250 ms inside its collection. From
the service it now covers the time since the previous reading, about one interval (`window_ms`). The JSON
types are the same, but the numbers average over a different window: a short burst weighs less.

The service's CPU baseline is the last successful reading, not the last published snapshot: when a
collection reads the CPUs and then fails on another sensor (or is dropped as too slow), nothing is
published, but the next window still starts at that reading, so it never spans readings that were not
taken. A window longer than the gap limit is not used. A `/proc/stat` read that fails, or has a `cpuN`
line with fewer than the 8 counters user..steal, fails the collection (`collection_failed`), is not used
as a baseline, and the next valid reading starts with `warmup`.

The service's first CPU reading is all `warmup`, so a snapshot made from it has `cpu: []` and is still a
normal, current snapshot (`ready`). Usually that is the first published snapshot; if the first collection
read the CPUs and then failed on another sensor, the first published one already has CPU usage.

Limits: CPUs that go offline and come back between two readings are not noticed (their counters continue
or are caught as `counter_regressed`); the lines of `/proc/stat` are not read at one instant.

When there is no current snapshot (none yet, or collection keeps failing), the answer is 503:

```json
{
  "error": "no current data (not collected yet, or collection keeps failing)",
  "schema_version": 1,
  "code": "no_current_data",
  "instance_id": "8dfad9fa-9bf0-4d61-91e0-ef22aebd2b91",
  "sample": {"sequence": 42, "age_ms": 6000.0, "data_age_ms": 6250.0}
}
```

`sample` describes the last good snapshot (null if there was none); its values are not included.
`/text` answers 503 with the `error` text only.

## `/api/status`

What the collector is doing now. Always HTTP 200: check `ready`, not the status code (the Docker health
check uses `/api/stats` for that reason).

```json
{
  "schema_version": 1,
  "instance_id": "8dfad9fa-9bf0-4d61-91e0-ef22aebd2b91",
  "state": "degraded",
  "ready": true,
  "sample": {"sequence": 42, "age_ms": 1100.0, "data_age_ms": 1350.0},
  "last_attempt": {
    "state": "error",
    "reason": "collection_failed",
    "completed_at": 1791345601.3,
    "duration_ms": 50.0,
    "consecutive_failures": 1
  },
  "collecting_for_ms": null,
  "clock": {"source": "boottime", "suspend_aware": true}
}
```

- `state`, `ready`:
  - `ready` (ready: true): the snapshot is current and the last collection succeeded.
  - `degraded` (ready: true): the snapshot is still current, but the last collection failed.
  - `starting` (ready: false): no snapshot and no failure yet, and the first collection has not run
    longer than `stale_after`.
  - `stale` (ready: false): anything else: the last snapshot is too old, or there never was one and the
    first collection failed or runs too long.
- `sample`: the last good snapshot, also when stale; null if there never was one.
- `last_attempt`: the latest finished collection, null before the first one finishes. `reason` is one of
  `collection_failed` (collect raised an error; details are in the service log, not in the API) and
  `collection_too_slow` (it took longer than `stale_after`). `consecutive_failures` resets on success.
- `collecting_for_ms`: how long the running collection has taken so far, null between collections. A
  growing value does not mean the reads are making progress.

## Clock

Durations and ages use `CLOCK_BOOTTIME` where available (`"source": "boottime"`), which keeps counting
while the device is suspended, so a snapshot from before a suspend shows its real age. Elsewhere platmon
falls back to the monotonic clock (`"source": "monotonic", "suspend_aware": false`), which may not count
suspended time, so ages can read too low right after a resume. Changes to the wall clock never affect them.

## Web page

The page shows `sample #N · data age S`: the server's `data_age_ms` plus browser time since that answer
arrived (transfer time is not included). Polling the same sample again does not reset it. On a failed
request it keeps the last good values and says they are not current. For an older server without
metadata it shows the time since its last answer instead, and says that it is not the sample's age.

CPUs listed in `cpu_sampling.unavailable` get a short note under the CPU rows ("CPU sampling: warming
up"), on the page and in the `platmon` command alike; they are not drawn as 0 %.
