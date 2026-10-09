# Remaining work

Status of the staged plan (Disk I/O → UI → storage capacity → PSI → Wi-Fi → RTT → history → release
readiness). Checked against the repository and devices whenever work resumes. Statuses: done, in
progress, waiting for validation, blocked (access), waiting for approval. Merging, production rollout
and releases always wait for the owner's approval.

Last update: 2026-10-09. main: `007a422` (#32–#38 merged).

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
