# Performance budget

## Default enablement policy update (2026-10-09)

After #40–#46 merged at `dc2875428892e99055e4dfe9c9afab0c2f7f1c52`, the owner requested
all monitoring features enabled by default. Network, Disk I/O, Storage, Wi-Fi, PSI, Probe and
History now default to enabled in both code and the shipped INI. Existing explicit off values
remain effective; omitted sections adopt the new defaults. Probe with no configured targets
stays idle without a worker, observation group or connection; targets require a restart to apply.
Unsupported hardware retains its existing unavailable result. No production configuration is changed.

This is an explicit policy choice, not a new performance pass. The previous supported all-on
measurement (PSI excluded, loopback Probe) reached 2.174% of one core in one Orin short window,
and 2.079% / 2.019% on Orin/Pi over retention. Storage/Wi-Fi call p95 still exceeds 2 ms.
The 2% target and raw results remain unchanged; the new exact default configuration has not
been ARM-benchmarked. Historical off-by-default statements below describe their measured revisions.

How platmon's CPU cost is judged before a feature ships or becomes a default. These are internal
product targets for a lightweight monitor, derived from the measurements in this directory. They are not
an industry standard, a safety limit for the host's own workload, or a real-time guarantee: average CPU
share says nothing about a task's worst-case latency or deadlines.

## Policy (since 2026-10-09)

| Level | Target | Role |
| --- | --- | --- |
| **Default configuration (release target)** | daemon CPU (user + system, the whole process) **≤ 2.0 % of one core** with every feature that is on by default | the gate for what runs by default |
| **Feature collection cost (review criterion)** | the increase in collector-thread CPU per collection (`Sampler._attempt`, so the feature's own call plus checking and publishing its data) **about ≤ 2 ms per collection**, reported next to the increase per request (`do_GET`) | finds expensive features early and starts a design review; not an automatic pass or fail |
| **Responsiveness** | a periodic passive collection's own call: elapsed p95 ≤ 2 ms | a low average must not hide a slow call |
| **Regressions** | no lasting memory growth, new collection failures, overruns, data-age fallbacks or data-ownership problems | correctness, apart from the numbers |

Conditions of the release target, judged **per board** (never averaged across boards, so one board
cannot hide another's excess): native process, collection every 1 s, one client reading `/api/stats`
every 1 s, reference instrumentation, 30 s warmup + 120 s windows in A B B A order, with the power mode,
governor, Python version and observed scope (sensors, interfaces) recorded. Boards: Jetson Orin Nano
and Raspberry Pi 4. The target is checked under these conditions; it is not a limit platmon holds under
any request rate, interface count or host load.

### Units

CPU % (pp for a difference) is `100 × Δ(user + system CPU s) / elapsed s` of the process over a measured
window, never divided by the CPU count. It is the number that is judged. Per collection and per
request costs (thread CPU in ms) explain where it goes:

    Δ CPU (pp) ≈ collections/s × Δ ms per collection / 10 + requests/s × Δ ms per request / 10 + other

This is an approximation for explaining a result, not a way to compute one. A longer interval does not
halve the cost if clients keep polling at the same rate, and the ms per collection also depend on the
board and the cadence.

### How a feature is decided

1. Measure the feature off / on in one tree (same SHA, only the feature's setting differs).
2. Check the feature criteria (collection ms, request ms, call p95, regressions). Above about 2 ms per
   collection, review the design before going further.
3. Check the release target for the configuration the feature would ship in. On by default only if
   the default configuration stays ≤ 2.0 % on every board; otherwise it ships off by default (opt-in)
   with its measured cost stated, or is reworked.
4. Write the measured cost in the feature's documentation.

Targets are set before a feature is measured. A feature that misses them does not get the target
raised for it. Estimates from adding up earlier per-part numbers are fine for planning, never for a
release decision: the integrated cost is measured on the configuration that includes everything already
on by default.

## Earlier policy (until 2026-10-09)

The earlier targets were a whole process ≤ 1 % of one core and a feature's increase ≤ 0.1 pp. Their
results stand as recorded:

- The whole process ≤ 1 % is not met by the current default without Network (Orin 1.42 %, Raspberry Pi
  1.23 %, [network-product.md](network-product.md) second round) nor in earlier reports. It remains a
  long-term improvement goal, no longer a release condition.
- Network's ≤ 0.1 pp is **not met** (`8cc82b0`: +0.141 / +0.197 pp; `31b4bbc`: +0.160 / +0.175 pp),
  with differences larger than the spread between repeats. That result is not changed by this policy.

Why it changed: with a fixed per-feature increase, the total is not controlled as features add up, while
most useful features would end up opt-in for missing a margin close to the measurement noise (repeats
differ by 0.02-0.09 pp), each needing about 30 minutes of windows per board to judge. A total for the
default configuration controls what users actually run; the feature criteria keep each addition visible.

## Network under this policy

Re-evaluated from the `31b4bbc` measurements; not a new experiment and not a new improvement.

| | Orin Nano | Raspberry Pi 4 |
| --- | --- | --- |
| whole process with Network on (release target ≤ 2.0 %) | 1.582 % | 1.402 % |
| collector-thread CPU per collection, off → on | 12.37 → 13.83 ms (+1.46) | 8.07 → 9.65 ms (+1.58) |
| request CPU (`do_GET`), off → on | 0.60 → 0.75 ms (+0.15) | 1.28 → 1.46 ms (+0.18) |
| the network call itself, mean thread CPU | 0.790 ms | 1.255 ms |
| network call elapsed p95 (≤ 2 ms) | 1.338 ms | 1.370 ms |
| regressions | none | none |
| headroom to 2.0 % (means) | about 0.42 pp | about 0.60 pp |

Network is therefore **on by default**, with `[network] enabled = no` to turn it off; an INI that already
says `no` stays off. Further features are measured on top of this configuration, and the headroom above
is not a reserved share for any of them.

## Disk I/O under this policy

Measured on top of Network on ([disk-io-product.md](disk-io-product.md), `e184f8c`, after one design
review: the first round missed the call p95 criterion on the Raspberry Pi).

| | Orin Nano | Raspberry Pi 4 |
| --- | --- | --- |
| whole process with Network and Disk I/O on (≤ 2.0 %) | 1.750 % | 1.558 % |
| collector CPU per collection, off → on | +1.46 ms | +1.12 ms |
| request CPU (`do_GET`), off → on | +0.05 ms | +0.08 ms |
| disk call elapsed p95 (≤ 2 ms) | 0.937 ms | 1.176 ms |
| regressions | none | none |
| headroom to 2.0 % (means) | about 0.25 pp | about 0.44 pp |

Disk I/O is therefore **on by default**, with `[disk_io] enabled = no` to turn it off.
