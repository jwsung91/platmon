# Remaining work

Status of the staged plan (Disk I/O → UI → storage capacity → PSI → Wi-Fi → RTT → history → release
readiness). Checked against the repository and devices whenever work resumes. Statuses: done, in
progress, waiting for validation, blocked (access), waiting for approval. Merging, production rollout
and releases always wait for the owner's approval.

Last update: 2026-10-09 13:30 KST. main: `85259427f20b` (#31, Network on by default). Merge order if approved: #32 → #33 → #34 → #36 → #37 → #38, and #35 after #33.

| # | Stage | Status | Branch / PR (base) | HEAD | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Disk I/O product | ready for review | `feat/passive-disk-io`, #32 (main) | `2d2c0c5` | CI 3.9/3.13; Orin/Pi off/on rounds `60962e3`, `e184f8c` ([disk-io-product.md](../performance/disk-io-product.md)); default on |
| 2 | Network / Disk I/O in CLI, web, `/text` | ready for review | `feat/network-disk-view`, #33 (#32) | `050cdba` | CI; Chromium desktop/narrow screenshots; no collection change |
| 3 | Storage capacity, low-frequency contract (`/api/observations`) | draft (cost measured; call p95 criterion not met, default off) | `feat/storage-capacity`, #34 (#33) | `1803480` | CI; Orin/Pi functional; per-observation cost, 2 rounds ([low-frequency.md](../performance/low-frequency.md)) |
| 4 | PSI | ready for review (normal path not verifiable on the boards; default off) | `feat/pressure-metrics`, #35 (#33) | `2a926d8` | CI incl. a real `/proc/pressure` read on the hosted runner |
| 5 | Wi-Fi signal (passive) | draft (cost measurement) | `feat/wifi-quality`, #36 (#34) | `e4f0c02` | CI; Orin/Pi functional |
| 6 | TCP connect probe (opt-in) | draft; no approved remote targets: loopback and fakes only | `feat/rtt-probe`, #37 (#36) | `9ea8af1` | CI; Orin/Pi loopback |
| 7 | Recent history (opt-in) | draft | `feat/recent-history`, #38 (#37) | `abe034b` | CI; memory bound measured locally |
| 8 | Integration, release readiness | in progress | `integration/release-candidate` (not for merging) | see branch | integrated service runs on Orin/Pi |

## Waiting for approval

- Production rollout of `8525942` (#31) to the Orin container and the Raspberry Pi process. On the Orin
  the candidate image `platmon:candidate-8525942` is built and smoke-tested (healthy, source ids equal to
  the running service, network ok in the container namespace), the running image is tagged
  `platmon:rollback-e1bc82a` and `~/platmon-rollback-e1bc82a-20261009-114530/` holds ROLLBACK.md, INI,
  compose files, CLI copy and inspect output (DEPLOY.md and SHA256SUMS are written at the switch). Not
  switched: the switch was refused by the session's permission check, and the later work order requires
  separate approval. Both devices still run `e1bc82a`.

## Device records

Bench and state records stay on each device, not only in a session's temporary directory:
`~/platmon-netbench-<sha>/` (Network), `~/platmon-diskbench-<sha>/` (Disk I/O),
`~/platmon-storagebench-<sha>/` and `~/platmon-obsbench-<sha>/` (low-frequency groups),
`~/platmon-rc-<sha>/` (integrated service); the later ones with `ops-before.txt` / `ops-after.txt`.
None of them is deleted by this work; removing old ones is the owner's decision.

## Test commands

```bash
pytest                                        # all tests; CI runs the same on Python 3.9 and 3.13
node tests/web_harness.js frontends/web/index.html
git diff --check
```
