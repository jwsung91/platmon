# Remaining work

Status of the staged plan (Disk I/O → UI → storage capacity → PSI → Wi-Fi → RTT → history → release
readiness). Checked against the repository and devices whenever work resumes. Statuses: done, in
progress, waiting for validation, blocked (access), waiting for approval. Merging, production rollout
and releases always wait for the owner's approval.

Last update: 2026-10-09. Resume baseline: `e1e7c9f38bfac83e9844ddb8110a9eae08a7fb5a`
(`origin/main`, #32–#39 already merged before this resumed task). The table below records historical
implementation; merging alone does **not** complete the expanded validation requirements.

## Merge checkpoint (2026-10-09)

The owner authorized necessary merges. #40 is merged at `4b1bc080`; its lifecycle tests and
viewer fixes are preserved in this branch. #41 retains the independently measured classifier
`1eae3a4` and the completed two-block ARM results in the Disk report. This merge resolves
documentation only; classifier and measured collector code are unchanged. Integration #46
contains the combined History, Storage and Wi-Fi work and is undergoing final bounded validation.
Production rollout and release publication remain unapproved.

## Historical resumed work checkpoint

- Branch: `feat/history-observation-contract`, stacked on Disk PR #41 at
  `1eae3a4bd5ddc6395d6c9c871e6af60b61041f27`; history follow-up PR pending.
  UI follow-up: #40, `33ada21`, signed; Python 3.9 CI 645/1, Python 3.13 CI 644/2 passed/skipped
  on push and PR event (runs 37891815033, 37891851001); branch `fix/frontend-observation-contract`.
  Clean worktree at entry. No user changes were present.
- Stage 1: **in progress**. Three classification-cache regressions reproduced and fixed; focused
  Disk/Network/provenance tests: **179 passed**. New ARM measurement required (plan in disk report); raw SHA-256 prefixes for the integrated
  `c2752c1` runs checked on both boards and matched. No collection changes in the UI follow-up.
- Stage 2: in progress. Reproduced missing observation windows, hidden zero in-flight counters, duplicate
  hanging optional HTTP requests and cached observations not becoming stale. CLI/web fixes and regression
  tests added; `pytest -v`: **643 passed / 3 skipped**, focused CLI/web: **68 passed**; final CI pending. Real Chromium fixture checks cover 1280/390 px, PSI/Wi-Fi panels, escaped
  labels, 503, a real 5 s timeout and 120 repeated renders (not a long-duration stability claim).
- Stages 3–6: implementations retained; validation still required against the complete work order.
  PSI normal-path ARM support and approved external probe targets remain unavailable; defaults stay off.
- Stage 7: **in progress, not complete**. Existing history explicitly excludes low-frequency groups;
  observation-ID-based append, explicit missing/elapsed-gap markers, gap-preserving downsampling,
  CPU/slow graphs and elapsed spacing implemented here. Wi-Fi gets namespace/index identity; no signal
  unit change. Local full tests: 654 passed / 3 skipped including the additional graph test;
  CI, real browser and real-time board retention verification pending. Maximum configuration synthetic
  tracemalloc: 22,505,990 bytes retained, 28,765,190 bytes peak with one read/JSON; targets 32/64 MiB.
- Stage 8: **waiting for validation**. Container/systemd isolation, board history retention, the second
  integrated ABBA block, and final exact-HEAD CI/measurement reconciliation remain outstanding.
- Devices rechecked over SSH: both production checkouts are `8525942`; Orin's original container and
  Pi's original process are running. No production modifications. Private state and local validation
  logs are in `.validation/20261009-resume/` (ignored), with original ARM raw still on the boards.
- Main CI run `37890446587`: Python 3.9 **642 passed / 1 skipped**, Python 3.13 **641 passed / 2 skipped**;
  Node-backed web tests and real hosted-runner PSI tests executed. These are baseline, not follow-up CI.
- Local baseline: `pytest -v`, Python 3.12, **640 passed / 3 skipped** with loopback allowed. The initial
  sandbox run failed on denied sockets; no assertions were weakened to accommodate the sandbox.
- Disk measurement is running in each board's `~/platmon-diskbench-1eae3a4/`, 8 windows (do not restart).
  Next: finalize the history PR and validate the integrated tree with #40.
  Nothing in this resumed task authorizes merging, production deployment or release publication.

## Historical implementation

| # | Stage | Status | PR | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Disk I/O product | merged; default on | #32 | Orin/Pi off/on rounds `60962e3`, `e184f8c` ([disk-io-product.md](../performance/disk-io-product.md)) |
| 2 | Network / Disk I/O in CLI, web, `/text` | merged | #33 | Chromium desktop/narrow screenshots |
| 3 | Storage capacity, `/api/observations` | merged; off (call p95 above 2 ms) | #34 | per-observation cost, 2 rounds ([low-frequency.md](../performance/low-frequency.md)) |
| 4 | PSI | merged; off (normal path not verifiable on the boards) | #35 | CI real `/proc/pressure` read on the hosted runner |
| 5 | Wi-Fi signal (passive) | merged; off (elapsed p95 above 2 ms) | #36 | Orin/Pi functional and cost |
| 6 | TCP connect probe | merged; off; no approved remote targets | #37 | loopback and fakes only |
| 7 | Recent history | merged; off | #38 | memory bound, integrated runs |
| 8 | Integration, release readiness | merged with this page | #39 | integrated service on Orin/Pi ([release-readiness.md](../release-readiness.md)) |

Not rolled out: #32–#38 (the devices run `8525942`, #31). Rolling them out is a separate decision.

## Rollouts

- Orin: switched to `8525942` (#31) on 2026-10-09 14:09 KST at the owner's request. Healthy, `/api/status`
  ready, network collector ok in the container's namespace (`eth0`, `lo`), the same 20 source records; the
  service used 1.32 % of one core over 60 s without clients. Rollback to `e1bc82a`:
  `~/platmon-rollback-e1bc82a-20261009-114530/ROLLBACK.md` (image `platmon:rollback-e1bc82a`; SHA256SUMS verify).
- Raspberry Pi: fast-forwarded to `8525942` and restarted the same way it was started (detached
  `python3 platmon.py platmon.ini`) on 2026-10-09 14:20 KST at the owner's request. `/api/status` ready,
  network ok (`eth0`, `lo`, `wlan0`), the same 5 source records, 0.97 % of one core over 60 s without
  clients, `get_throttled` 0x0. Previous log: `~/platmon.log.e1bc82a`; to go back, `git switch --detach
  e1bc82a` in its checkout and restart the same way.

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
