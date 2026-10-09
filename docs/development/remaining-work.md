# Remaining work

Status of the staged plan (Disk I/O → UI → storage capacity → PSI → Wi-Fi → RTT → history → release
readiness). Checked against the repository and devices whenever work resumes. Statuses: done, in
progress, waiting for validation, blocked (access), waiting for approval. Merging, production rollout
and releases always wait for the owner's approval.

Last update: 2026-10-09. main: `85259427f20b` (#31, Network on by default).

| # | Stage | Status | Branch / PR | HEAD | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | Disk I/O product | ready for review (waiting for approval to merge) | `feat/passive-disk-io`, #32 | see PR | `pytest`; CI 3.9/3.13; Orin/Pi off/on rounds `60962e3`, `e184f8c` ([disk-io-product.md](../performance/disk-io-product.md)) |
| 2 | Network / Disk I/O in CLI, web, `/text` | pending | - | - | - |
| 3 | Partitions and filesystem capacity (low-frequency contract) | pending | - | - | - |
| 4 | PSI | pending; `/proc/pressure` absent on Orin, Raspberry Pi and WSL as of 2026-10-09 (normal path not verifiable on them) | - | - | - |
| 5 | Wi-Fi quality (passive) | pending | - | - | - |
| 6 | Opt-in RTT | pending; no approved targets: fakes and loopback only | - | - | - |
| 7 | Recent history | pending | - | - | - |
| 8 | Integration check, release readiness | pending | - | - | - |

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
`~/platmon-netbench-<sha>/` (Network), `~/platmon-diskbench-<sha>/` (Disk I/O, with `ops-before.txt` /
`ops-after.txt`).

## Test commands

```bash
pytest                                        # all tests; CI runs the same on Python 3.9 and 3.13
node tests/web_harness.js frontends/web/index.html
git diff --check
```
