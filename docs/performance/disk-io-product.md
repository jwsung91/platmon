# Product Disk I/O off / on

What the product's Disk I/O collection ([../disk-io.md](../disk-io.md)) costs on top of the current
default configuration, judged by [budget.md](budget.md). A and B are the same product and bench code with
`[disk_io]` off (A) and on (B); Network is on in both arms (it is on by default), and the passive prototype
is never called.

## Result (2026-10-09)

| | Orin Nano | Raspberry Pi 4 |
| --- | --- | --- |
| **Release target**: whole process with Network and Disk I/O on ≤ 2.0 % of one core (`e184f8c`) | **met**: 1.750 % (largest run 1.944 %) | **met**: 1.558 % (largest run 1.595 %) |
| Disk I/O on − off, whole process (`e184f8c`) | +0.152 pp (blocks +0.209, +0.095); the spread between repeats (0.263 pp) is larger, so the size is not precise | +0.123 pp (blocks +0.160, +0.085); spread 0.131 pp, likewise |
| Collector CPU per collection, off → on (review criterion, about ≤ 2 ms) | +1.46 ms | +1.12 ms |
| Request CPU (`do_GET`), off → on | +0.05 ms | +0.08 ms |
| Disk call elapsed p95 (≤ 2 ms) | **met**: 0.937 ms (max of per-run p95 0.950) | **met**: 1.176 ms (1.189) |
| Regressions | none: 0 failed collections, overruns, data-age fallbacks, HTTP or client errors; RSS end on − off −1.49 MiB | none; RSS −0.16 MiB |

So Disk I/O is **on by default** (`[disk_io] enabled = yes`, and `no` turns it off).

- Two rounds. The first (`60962e3`) missed the call p95 criterion on the Raspberry Pi (2.47 ms) and was
  above the about-2 ms review criterion for the collection (+2.38 ms). Review found a concrete cause: the
  parser converted and checked the counters of every row of `/proc/diskstats` (28 rows on the Pi, 41 on the
  Orin) although one disk is collected. The second round (`e184f8c`) converts only the rows of collected
  disks; the left-out rows are matched by name only. The call's mean thread CPU went from 1.170 to
  0.671 ms (Orin) and 2.264 to 1.071 ms (Raspberry Pi). The two rounds are separate sessions; the
  process-level differences between them are a reference, not a measured effect of the change.
- Second-half RSS growth was ≤ 16 KiB in every run except one off run on the Orin in round 2 (2024 KiB)
  and one on run on the Orin in round 1 (1052 KiB): single steps in either arm, not repeated, not a trend
  of the feature.

## Setup

| | |
| --- | --- |
| Rounds | 1: product `60962e3` (product hash `6384d86f718a5113`); 2: product `e184f8c` (hash `174ee0526c7e6400`); bench hash `426b0cda6046a6df` in both |
| Runs | `cadence.py run --phase disk-product --clients 1 --blocks 2`: variant B0 (passive no-op), `--product-network on` in every run, `--product-disk off` or `on`; collection 1 s, one client polling `/api/stats` at 1 s, reference instrumentation, 30 s warmup + 120 s window, a new process per run; blocks c1-1, c1-2, each off on on off |
| What on runs | `collect_recorded(..., NetworkCounters, DiskCounters)`: the diskstats read, the `/sys/block` lookups of new names, rates, `collectors.disk_io`, `disk_io.read` checked by the Sampler; each `DiskCounters.sample` call timed |
| What off runs | `collect_recorded(..., NetworkCounters, None)`: no diskstats or `/sys/block` read in the window (0 disk calls in every off run); the disk scope from one reading after the window |
| Comparable | per block: same alias, interval, clients, Python, product and bench hash, sensors, collectors (without `collectors.disk_io`), network namespace and interfaces, disk names: no mismatch |
| Budget | per board and round 8 windows / 20.2 min of runs (round budget 30 min / 8 windows) |

| alias | hardware, OS | Python | clock policy | disks collected (rows in `/proc/diskstats`) |
| --- | --- | --- | --- | --- |
| orin | Jetson Orin Nano devkit (Super), L4T R36, 5.15-tegra, native | 3.10.12 | MAXN_SUPER, `schedutil` | 1 NVMe disk (41 rows: loop, zram, partitions) |
| rpi4 | Raspberry Pi 4 Model B, Debian 13, 6.18 rpi-v8, native | 3.13.5 | `ondemand` | 1 SD card (28 rows: ram, loop, zram, partitions) |

Every run valid; no skipped run, timeout or clock jump. `get_throttled` 0x0 after every Raspberry Pi run;
hottest zone after each run 52.7-53.1 °C (Orin), 51.6-54.5 °C (Raspberry Pi). The boards' own services
(`e1bc82a`) kept running untouched: a full state record (container id, image, start time, restart count,
health; process and start time; checkout SHA, clean tree and INI hash; images and rollback folders with
their SHA256SUMS; power mode; governors; service answer and `instance_id`) was written on each device
before round 2 and again after it, and the two are the same. Round 1 has a record from before it only; the
record before round 2 (taken right after round 1) matches it.

## Table 1 — Disk I/O off / on (CPU % of one core, user + system, 120 s windows)

| board | round | block | off runs | on runs | on − off pp |
| --- | --- | --- | --- | --- | --- |
| orin | 1 `60962e3` | c1-1 | 1.610, 1.603 | 1.741, 1.727 | +0.128 |
| orin | 1 | c1-2 | 1.587, 1.577 | 1.733, 1.727 | +0.149 |
| orin | 1 | **all** | mean 1.594 | mean 1.732 | **+0.138** (spread 0.033, distinguishable) |
| orin | 2 `e184f8c` | c1-1 | 1.595, 1.618 | 1.686, 1.944 | +0.209 |
| orin | 2 | c1-2 | 1.576, 1.607 | 1.681, 1.691 | +0.095 |
| orin | 2 | **all** | mean 1.599 | mean 1.750 | **+0.152** (spread 0.263, indistinguishable) |
| rpi4 | 1 `60962e3` | c1-1 | 1.431, 1.434 | 1.747, 1.757 | +0.319 |
| rpi4 | 1 | c1-2 | 1.454, 1.442 | 1.556, 1.678 | +0.169 |
| rpi4 | 1 | **all** | mean 1.440 | mean 1.685 | **+0.244** (spread 0.201, distinguishable) |
| rpi4 | 2 `e184f8c` | c1-1 | 1.415, 1.450 | 1.595, 1.591 | +0.160 |
| rpi4 | 2 | c1-2 | 1.439, 1.437 | 1.582, 1.464 | +0.085 |
| rpi4 | 2 | **all** | mean 1.435 | mean 1.558 | **+0.123** (spread 0.131, indistinguishable) |

Definitions as in [network-product.md](network-product.md): CPU % = 100 × Δ(user + system CPU s) /
measured elapsed s, never divided by the CPU count; block delta = mean of its on runs − mean of its off
runs; spread = largest − smallest run of one arm.

## Table 2 — Where it goes (means; pooled percentiles over all 480 calls per row)

| board | round | disk call thread CPU mean / p50 / p95 ms | elapsed p95 / max ms | `_attempt` CPU off → on ms | `do_GET` CPU off → on ms | response KiB off → on |
| --- | --- | --- | --- | --- | --- | --- |
| orin | 1 | 1.170 / 0.914 / 1.907 | 1.922 / 2.018 | 13.95 → 15.31 | 0.74 → 0.77 | 10.3 → 11.0 |
| orin | 2 | 0.671 / 0.555 / 0.930 | 0.937 / 1.079 | 13.99 → 15.45 | 0.73 → 0.79 | 10.3 → 11.0 |
| rpi4 | 1 | 2.264 / 2.330 / 2.472 | 2.469 / 2.559 | 10.00 → 12.38 | 1.47 → 1.53 | 4.3 → 4.9 |
| rpi4 | 2 | 1.071 / 1.082 / 1.178 | 1.176 / 1.333 | 10.01 → 11.13 | 1.46 → 1.53 | 4.3 → 4.9 |

The whole-process difference (Table 1) also contains the publish and request side; Table 2's
per-collection and per-request numbers explain it and are not added to it.

## Reproduce

```bash
python3 benchmarks/cadence.py run --out DIR --alias NAME --phase disk-product --clients 1 --blocks 2 \
    --budget-min 30 --max-windows 8 --watch-url http://127.0.0.1:9797/api/stats --source-sha e184f8c
python3 benchmarks/cadence.py report --md DIR/results.jsonl
```

Raw files stay on each device in `~/platmon-diskbench-<sha>/raw-<alias>/results.jsonl`, next to
`ops-before.txt` / `ops-after.txt` (not in the repository):

| round | alias | `results.jsonl` SHA-256 |
| --- | --- | --- |
| 1 | orin | `074caf86e89d6d707cfc74aec8530d3719ba06e5f0f5279b8cfabfec0582eca9` |
| 1 | rpi4 | `9c22089891354f501822595218aa1b91656ef8f443d6018aa17eba1bcdab89b1` |
| 2 | orin | `6e31ab33677f8f2b834349ca75c8cef6ff6e4a443b77350243249b1ae6bba59b` |
| 2 | rpi4 | `eb8e2379fbb50c01547898e97fff1886e72393565b56ca5fc2fb3d8f984d04b9` |

## Classification correctness follow-up (measurement pending)

The resumed audit found that the previous name-only cache survived device-number changes and whole-file
failures, and permanently cached a missing sysfs link. The follow-up keys confirmed classifications by
major/minor/name, clears the cache on failed reads and retries missing links (including partitions).
This changes collection cost: **the historical numbers above are not validation of this new path**.

Plan before measurement: same signed product/bench SHA, Disk off/on with Network on in both arms,
reference instrumentation, native 1 s collector and one 1 s client; 30 s warmup + 120 s per window;
two ABBA blocks per board, 8 windows, at most 50 minutes/16 windows per board including at most one
cause-driven optimization round. Acceptance stays CPU ≤2% and call elapsed p95 ≤2 ms, no new errors,
overruns, freshness fallback or sustained memory growth. No stress load, operating setting change or
production restart. The existing default-on decision is historical until this follow-up is measured.
