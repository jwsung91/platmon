# History expiry correction validation (2026-10-09)

## Reassessment after a reproduced retention defect

The recovery-gap candidate `65bcc39` still retained expired low-frequency points internally.
With retention 600 s, a fake-clock Storage series retained 20, 40 and 60 points at 600, 1200
and 1800 s, although the latter HTTP views showed only 21 points. The shared core-cadence
deque cap was bounded, but slow publishers could keep allocating for hours after the visible
window filled. This invalidates a post-fill memory stability claim for that candidate.

#42 `a52880b77294930aa78c61d13cc2e4390e09e267` removes expired points when their publisher
appends. The cutoff is inclusive: a point exactly at the boundary remains. No HTTP mutation,
new worker, dependency, default, public field or request policy is introduced. Storage, Wi-Fi
and Probe regression cases failed before the two-line correction; focused History/Sampler
tests pass 53/53 and component full tests pass 665 with 3 skips.

The preceding board round is preserved, not extended or relabeled as validating this fix.
The user's requested scoped correctness repair and validation of the new SHA require a new
measurement. This is a reassessment after a failed correctness hypothesis, not a retry to
improve a marginal performance result. The CPU and responsiveness targets are unchanged.

## Fixed validation scope before running

- One new round, at most 60 minutes per board, after the previous runner has finished and
  released its process and port. No overlapping benchmarks or production changes.
- Archive the final integrated correction with its source and runner hashes in a new
  `~/platmon-expiry-rc-<sha>/` directory. Never edit the previous measured checkout.
- Same default/all ABBAABBA: 30 s warmup + 120 s measurement, one stats client at 1 s and
  observations/history at 10 s; default Network/Disk on, other features off.
- Same all-on 30 s warmup + 1800 s retention measurement, retention 600 s. Compare RSS/PSS
  after filling across two more 600 s windows, record ranges/slopes, bounds and identities.
- Default CPU must remain <=2% on each board. Report all-on CPU separately, including any
  miss; require zero recorded failures/drops/fallbacks and no observed collection overruns.
  Sampled timing cannot prove every attempt's duration.
- Reuse only unchanged-path evidence: browser fixtures/661 s soak and independent Disk,
  Storage/Wi-Fi cadence costs. Their optional p95 misses remain failures and defaults stay off.
- After native measurements, validate the same SHA using existing Orin compose files with
  a unique project/image, loopback port, non-root/read-only/cap-drop/no-new-privileges settings.
  The earlier prepared container run is superseded; avoid a redundant old-code build.
- Preserve raw results and rollback material; compare operational identities before/after.
  Actual privileged systemd execution, ARM PSI and external TCP remain unavailable/unapproved.

If this correction still fails a required gate, preserve the failed evidence and Draft status;
do not silently retry or change thresholds. Final CI and measured SHA are recorded with results.

## Results

Pending the declared round.
