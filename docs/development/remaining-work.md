# Remaining work

Status of the staged plan (Disk I/O → UI → storage capacity → PSI → Wi-Fi → RTT → history → release
readiness). Checked against the repository and devices whenever work resumes. Statuses: done, in
progress, waiting for validation, blocked (access), waiting for approval. Merging, production rollout
and releases always wait for the owner's approval.

Last update: 2026-10-09. Resume baseline: `e1e7c9f38bfac83e9844ddb8110a9eae08a7fb5a`
(`origin/main`, #32–#39 already merged before this resumed task). The table below records historical
implementation; merging alone does **not** complete the expanded validation requirements.

## Current checkpoint — authorized final validation

The owner authorized necessary merges on 2026-10-09. #40, #43 and #41 are merged;
main is `efb3af6c12873195f9b3cfe23ad68cbd5ff802b3`, with successful main CI.
#42 now targets main; #44 follows its updated head. Neither duplicates Disk work in its diff.
The seven-stage post-integration request is at 3/7 complete (status, frontend, Disk), with
History ARM and final integration validation running. Production remains `8525942`.

Exact measured candidate: `30d377a9b7cd470d655367398dab39c3b1f5313a`. The
[final plan](../performance/final-candidate-plan.md) fixes a 60-minute board budget for two
ABBA blocks and 1830 s retention; it supersedes the earlier stop after 660 s. The earlier
CPU matrix overlapped an independent validation and is historical, not the final gate.
Local final runtime tests: 672 passed / 3 skipped; candidate CI 37904134307/37904140826
passed on Python 3.9 and 3.13. Runtime files in the merged component branches are identical.
Final-page Chromium fixtures pass; the 660 s real-page soak is running.

Actual systemd DynamicUser execution still needs administrator authentication; Pi unit syntax
verification passes. PSI remains unsupported on ARM; no external TCP target is approved.
These documented limits do not authorize privilege workarounds or production changes.
Raw evidence is in `.validation/final-rc-evidence/` and `~/platmon-final-rc-30d377a/`.

## Historical checkpoint — resumed integration

The eight requested stages have **4/8 completed within the documented support scope** (1, 2, 3, 5).
Stages 4 and 6 have implementation/automated checks but environment or target validation gaps;
stage 7 has working retention and bounded-allocation evidence but insufficient real post-fill duration
for long-term stability; stage 8 remains Draft. No stage count includes merge or deployment.

Main is unchanged at `e1e7c9f38bfac83e9844ddb8110a9eae08a7fb5a`. Production on both boards is
`85259427f20ba09c9541c52970243fc07645d21d`, verified before/after the experiments. The original
#32–#39 were already merged when this task resumed. They were reused, not rebuilt.

| Stage | Current state | Follow-up PR / branch / verified code HEAD | Evidence / remaining limit |
| --- | --- | --- | --- |
| 1 Disk | complete, review ready | #41 `fix/disk-classification-identity` / `2aa7d793df552688ae39aced58020fe4c2ae551e` | measured `1eae3a4`, 8 windows per ARM, CPU and p95 pass; default on |
| 2 UI | complete, review ready | #40 `fix/frontend-observation-contract` / `ee3142247093b95780a6e881232075c2b8264531` | bounded polling, age, units; actual Chromium 1280/390, XSS, 503, timeout, synthetic visibility event |
| 3 Storage | complete for directory mounts, review ready | #43 `fix/storage-mount-race` / `e0dee298f6c50af9ec4c5e9adcdf5c6e3cf12ed5` | descriptor identity fix; ARM normal path; container file-bind capacities unavailable; off, call p95 fails |
| 4 PSI | normal ARM validation blocked by unsupported kernels | existing #35 in main | fixtures and hosted Linux normal path pass; both ARM/WSL lack pressure files; off |
| 5 Wi-Fi | complete for documented provider, review ready | #44 `fix/wifi-connection-state` / `ab875197e3708347f4031a25866126879f357a13` | carrier/ifindex validation; real negative dBm on both ARM; off, call p95 fails |
| 6 TCP probe | remote validation waiting for approved target | existing #37 in main | fake/deadline/error and own loopback checks; no arbitrary target; off |
| 7 History | implementation/tests complete; extended stability pending | #42 `feat/history-observation-contract` / `9555c235d999c45fd5899f4a48d1e77e099e44e1` | independent low-frequency append, gaps, strict limits; 660 s ARM retention; only 60 s after fill, no long-term plateau claim; off |
| 8 Integration | Draft; systemd access blocked | #46 `integration/resumed-release-readiness` | measured `e919baf72a5c5100dd5468188fcc97b119b287f6`; combined #45 follow-up at `2a0e209`; final documentation HEAD is the commit containing this checkpoint |

PR #45 (`integration/post-integration-rc`, `8df75e8`) was reconciled into #46, retaining its UI/tests/bench
improvements and this task's Storage/Wi-Fi fixes. Its earlier open-gate report is historical context;
[resumed results](../performance/resumed-integration-results.md) supersede the pending ARM entries.
#42 depends on #41; #44 depends on #42; #46 includes #40–#45. Review component diffs against their PR
bases, not the full aggregate as a new feature. No force-push, main merge or commit rewrite.

Validation: final combined `pytest -v` **672 passed / 3 skipped** (Python 3.12); all Node harnesses run
through pytest; actual Chromium fixture passed after reconciliation. Before the display-only
reconciliation, #46 CI run 37898089620 passed 672/1 (3.9), 671/2 (3.13), including hosted real PSI and
Node. Final exact-HEAD CI is linked in PR #46; its original logs are retained privately. See the release
readiness page for the complete evidence boundaries and commands.

Private raw/state/CI/screenshots: `.validation/20261009-resume/`, and durable board directories
`~/platmon-diskbench-1eae3a4/` and `~/platmon-resume-e919baf/`. Both suites ended normally. Older raw and
rollback material remain intact. Operational records are private; public reports contain anonymized
summaries and hashes. No extra ARM performance rounds after the predeclared budget.

Next executable gate: isolated production-style systemd validation with existing administrator
authentication. `sudo -n true` requires a password on the available hosts; no credential request,
new capability or production-unit change is used to bypass it. Extended history stability needs a
separately recorded experiment budget. Remote TCP needs an owner-selected allowlisted target; PSI
normal ARM validation needs an already-supported environment, without reboot/kernel changes.

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
