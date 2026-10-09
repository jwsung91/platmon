# Low-frequency observations (`/api/observations`)

Some data changes slowly or is slow to read: filesystem capacity today, later possibly others. Such a
group is observed on its own cadence by its own thread, apart from the core Sampler, and served at
`/api/observations` with its own id, times and age. `/api/stats` (the 1 s snapshot) is unchanged and never
contains these groups, so an old or blocked observation can never make the core snapshot stale or 503.

```json
{
  "schema_version": 1,
  "instance_id": "8dfad9fa-9bf0-4d61-91e0-ef22aebd2b91",
  "clock": {"source": "boottime", "suspend_aware": true},
  "groups": {
    "storage": {
      "state": "ok",
      "interval_ms": 30000.0,
      "stale_after_ms": 90000.0,
      "collecting_for_ms": null,
      "observation": {"id": 12, "started_at": 1791345600.0, "completed_at": 1791345600.004,
                      "duration_ms": 4.2, "age_ms": 7000.0, "data_age_ms": 7004.2, "stale": false},
      "collector": {"state": "ok", "reason": null, "issues": [], "issues_truncated": 0},
      "data": {"partitions": [], "filesystems": []}
    }
  }
}
```

- Always HTTP 200 with `Cache-Control: no-store`, also with no group enabled (`groups: {}`). Requests
  only read the latest published observation; they never trigger one.
- `instance_id` is the service's (as in `/api/stats`); `observation.id` counts this group's observations
  from 1 and is not the core `sample.sequence`. The same id read again is the same observation.
- Times: `started_at`, `completed_at` are wall-clock seconds, for people. `duration_ms`, `age_ms` (since it
  completed) and `data_age_ms` (since it started: the oldest read in it) are on the elapsed clock of
  `clock`, as of this answer, so they keep growing while the same observation is served.
- `interval_ms`: the configured time between starts. `stale_after_ms`: 3 intervals. `stale` is true once
  `data_age_ms` is above it.
- `state`: `starting` (no observation yet), `stale` (the last observation is older than `stale_after_ms`,
  or the first one is still running after that long), otherwise the C1 state of the latest observation
  (`ok`, `partial`, `error`, `unavailable`; see [api.md](api.md#optional-metrics)). A stale observation is
  still served with its `data`, marked `stale`, never as current; clients show it as not current.
- `collecting_for_ms`: how long the running observation has taken so far, `null` between them. A read
  that blocks (a hung filesystem) stalls only its own group: the group's age grows and this value says for
  how long. platmon cannot cancel a blocked read, and does not start another thread for the group while it
  is blocked, so the next observation of that group starts only after it returns.
- `collector`, `data`: the group's C1 diagnostics and data from that observation, published as one unit
  and never changed afterwards.

Clients ask for `/api/observations` on the groups' cadence, not every second: the web page and the
`platmon` command ask at most every 10 s (the page only while it is visible) and add the time since that
answer to the ages shown. A server without the endpoint (404) is not asked again.

Groups: `storage` ([storage.md](storage.md)), `wifi` ([wifi.md](wifi.md)).
