# Release readiness (integration of #32–#38)

## Current final candidate status (2026-10-09)

The owner authorized necessary merges. #40, #43 and #41 are merged; main CI passed.
#42 targets main, #44 follows #42, and #46 preserves all components and #45's validation work.
The current candidate runtime is `aac7ed796faf2be0e387312c04a78925198fe11d`; remaining component
merges await the declared ARM gates. **The candidate remains Draft, not a release or deployment.**

Two reproduced History defects are corrected: one failed core attempt now inserts a graph break,
and each publisher releases expired points instead of retaining slow observations until the shared
core-cadence count cap fills. Focused tests pass 53/53; integrated tests pass 676/3 locally and
678/1 (Python 3.9), 677/2 (Python 3.13) in candidate CI 37913085542. The unchanged frontend retains
its 1280/390 px Chromium fixtures and 661 s soak (constant DOM, no JS errors).

[Pre-correction results](performance/final-candidate-results.md) and the
[recovery-gap round](performance/recovery-gap-validation.md) remain historical measurements.
The reproduced expiry defect prevents using them as proof of post-fill memory stability.
The [expiry correction plan](performance/history-expiry-validation.md) records the new bounded
measurement scope before execution. Actual RSS, default CPU and isolated Orin compose results
will decide the remaining merges; no sampled timing is described as full per-attempt accounting.

Network/Disk remain on; Storage/PSI/Wi-Fi/TCP/history remain off. Storage/Wi-Fi call p95 still
exceeds 2 ms. Actual systemd DynamicUser execution is unverified because administrator
authentication is unavailable; Pi unit static verification succeeds. ARM PSI is unsupported and
no external probe target is approved. Production stays at `8525942`; deployment, tags, releases
and registry pushes remain unapproved. The historical rollback procedure below is not executed.

## Historical resumed candidate status (2026-10-09)

**Review candidate; not fully release-ready.** #46 combines #40–#44 and the concurrent #45 follow-up
without modifying main. Exact component HEADs and eight-stage status are in
[remaining-work.md](development/remaining-work.md). The previous candidate report is preserved as
[historical context](development/post-integration-validation.md); its pending ARM entries are
superseded by the [new measured results](performance/resumed-integration-results.md).

The measured service/collector tree is `e919baf72a5c5100dd5468188fcc97b119b287f6`. Subsequent #45
reconciliation changes web age rendering, tests, benchmark diagnostics and docs; its collector,
server, CLI and service entrypoint are identical to the measured tree. Reuse is limited to those
unchanged paths. Final branch HEAD is available on PR #46; documentation commits are not measurement
SHAs. No main merge, production rollout, tag, Release or registry image publication.

### Changes and compatibility

Disk classifications are invalidated on identity changes/read failure and failed sysfs access is
retried. UI uses bounded optional requests, validates return epochs and keeps ages advancing.
Storage verifies the opened directory's device identity before capacity reads. Wi-Fi validates
carrier and ifindex instead of inferring connectivity from wireless update punctuation. History
stores independent observations once, represents missing intervals explicitly and bounds requests,
series and storage. No new runtime dependency, general scheduler or per-request collection.

`/api/stats` and `/api/history` retain schema 1. `/api/observations` becomes **schema 2** because
Wi-Fi `connected` can now be null and has an explicit `connection_state`; see
[the version boundary](observations.md). New CLI/web handle v1/v2. Legacy root `disk`, 503/no-store
and remote standalone CLI remain intact. Network/Disk stay on; Storage/PSI/Wi-Fi/TCP/history stay off.

### Validation and limits

- `pytest -v`: final reconciled local tree **672 passed / 3 skipped**. Skips: two profiling capability
  checks and unsupported local PSI. CI before reconciliation: Python 3.9 672/1, Python 3.13 671/2
  (run 37898089620), including Node and real hosted-runner PSI. Final exact-HEAD CI is attached to #46;
  raw logs distinguish push HEAD from the PR merge ref.
- Real Chromium after reconciliation: desktop 1280 px / narrow 390 px, logo, escaping, missing fields,
  pressure/Wi-Fi fixture panels, 503, actual 5 s timeout and simulated visibility-return event. This
  is an actual browser with fixtures, not actual hardware PSI or a real OS tab lifecycle test.
- A live container page at measured `e919baf` ran 661 s: 661 stats and 65 each observations/history
  requests, zero JS/page errors, 289 live DOM nodes throughout. Renderer task time 4.405 s and final
  JS heap 2.86 MB are browser metrics, not daemon CPU. This long run predates the final history-age
  repaint; the reconciled page passed bounded repeated-render fixture checks, not another long soak.
- Native legacy INI, explicit Network/Disk off, each optional group and standalone copied CLI passed.
  Enabled TCP without targets is rejected at startup (exit 2), before listener/probe creation.
  Six valid services exited normally and released their isolated ports.
- Existing Dockerfile was built locally at `e919baf`, then run non-root (UID 65534), read-only,
  cap-drop ALL, no-new-privileges on an isolated loopback port. Core, history and own-loopback TCP
  worked; Storage reported null/io_error on file bind mounts, overlay was excluded, Wi-Fi/PSI were
  unsupported. Namespace scope was inspected; this container is not evidence of whole-host visibility
  or of Orin-specific container hardware support. No production compose/network was changed.
- ARM two-block default/all matrix: default **1.59–1.64% Orin / 1.54–1.60% Pi**, every window ≤2%.
  Storage elapsed p95 **3.212/3.223 ms**, Wi-Fi **3.365/7.871 ms** exceed 2 ms: off remains. The cost
  criterion was not changed. The integrated tool does not count every collection overrun/drop;
  separate Disk reference instrumentation does not remove that combined-path evidence limitation.
- Both boards completed 660 s history retention with unique publication IDs and bounded responses.
  Only about one minute follows the first full window; **long-term RSS plateau remains unverified**.
  Maximum-allocation synthetic memory evidence is separate from real RSS. No budget extension.
- Production before/after checkout, INI, instance and process/container identities matched at
  `8525942`. Private raw/hash manifests, scripts and screenshots are preserved; see the result report.

Open gates: actual DynamicUser/ProtectSystem/ProtectHome systemd execution is blocked by existing
administrator authentication; normal PSI on the ARM kernels is unsupported; remote TCP targets are
not approved. Longer post-fill history and final-page soak need a new bounded validation plan.
These limits keep #46 Draft; successful fixtures are not substituted for missing environments.

The historical installation/rollback procedure below remains a proposal for a separately approved
fixed merged SHA. Preserve existing images, INI, CLI and checkout before any switch. No step was
executed by this resumed task. New installs use defaults above; existing explicit off values remain.

## Historical integration evidence

Status of the features built on top of main `85259427f20b` (#31), checked together on the
`integration/release-candidate` branch before they were merged. All of them are on main now (#32 → #33 →
#34 → #36 → #37 → #38, then #35; main `007a422`); each was merged on its own PR with its tree checked equal to
the PR head and main's CI green after it. Nothing here is released, tagged or deployed: the devices run
`8525942` (#31), see below.

## Contents and defaults

| PR | Feature | Default | API | Docs |
| --- | --- | --- | --- | --- |
| #31 (merged) | Network counters | **on** | `/api/stats` `network` | [network.md](network.md) |
| #32 | Disk I/O counters | **on** | `/api/stats` `disk_io` | [disk-io.md](disk-io.md) |
| #33 | Network / Disk I/O in the web page, `platmon` command, `/text` | - | - | [api.md](api.md#web-page) |
| #34 | Storage capacity; low-frequency groups | off | `/api/observations` (new) | [storage.md](storage.md), [observations.md](observations.md) |
| #35 | Pressure stall information | off | `/api/stats` `pressure` | [pressure.md](pressure.md) |
| #36 | Wi-Fi signal (passive) | off | `/api/observations` `wifi` | [wifi.md](wifi.md) |
| #37 | TCP connect probe (active) | off, no targets | `/api/observations` `probe` | [probe.md](probe.md) |
| #38 | Recent history | off | `/api/history` (new) | [history.md](history.md) |

Merged in that order on 2026-10-09; #35 last, after #38, so its conflicts with the storage to history
features were resolved once (taking the integration branch's resolution, checked against main).

## Compatibility

- `/api/stats` keeps every existing key, unit and type and `schema_version` 1. New keys: `network`,
  `disk_io` (on by default), `pressure` (when enabled), and the matching `collectors` entries. `disk` (root
  filesystem usage) is unchanged and separate from `disk_io`.
- `/api/status`, `/text`, `/` and their status codes, 503 rules and `no-store` are unchanged; `/text`
  shows more lines. New read-only endpoints: `/api/observations` (always 200), `/api/history` (404 while
  history is off). Older clients ignore them; the new page and command handle servers without them
  (nothing shown, not asked again after a 404).
- Config: new sections `[network]`, `[disk_io]` (on), `[pressure]`, `[storage]`, `[wifi]`, `[probe]`,
  `[history]` (off). An existing INI without them gets the defaults; an explicit `enabled = no` is kept;
  unknown keys are still refused.
- The `platmon` command stays one standard-library file; it never imports the collector.

## Cost (integrated, `c2752c1`; later commits change only the display of long mount lists and docs)

The real service (`python3 platmon.py INI`, native) polled like the web page (`/api/stats` every 1 s,
`/api/observations` and `/api/history` every 10 s) by `benchmarks/service_cpu.py` from its own process;
the service's user + system CPU from `/proc/<pid>/stat`; 30 s warmup + 120 s window; order default, all,
all, default.

| board | default (Network + Disk I/O on) | all on (+ storage, Wi-Fi, probe to loopback, PSI, history) | target |
| --- | --- | --- | --- |
| Jetson Orin Nano | 1.583, 1.669 % (mean 1.626) | 1.817, 1.742 % (mean 1.779) | ≤ 2.0 %: met by both |
| Raspberry Pi 4 | 1.567, 1.595 % (mean 1.581) | 1.835, 1.860 % (mean 1.847) | ≤ 2.0 %: met by both |

RSS at the end of the windows 23.8–26.5 MiB in every run. `/api/stats` answered 120–121 times per window
without an error (largest latency 4.3 ms Orin, 5.6 ms Raspberry Pi); with history off `/api/history` is the
expected 404. History was not full in a 150 s run: its bound is 3.5–3.7 MiB at 600 s
([performance/low-frequency.md](performance/low-frequency.md)). PSI is unsupported on both boards, so the
"all on" runs include its unsupported path only.

Per-feature results and the criteria not met:

| feature | per-feature result | criteria |
| --- | --- | --- |
| Network | +0.160 / +0.175 pp (`31b4bbc`) | met under [budget.md](performance/budget.md); the earlier 0.1 pp target is recorded as not met |
| Disk I/O | +0.152 / +0.123 pp, call p95 0.94 / 1.18 ms (`e184f8c`) | met |
| Storage | 2.8–3.1 ms per observation every 30 s (≈ 0.01 pp) | call p95 ≤ 2 ms **not met** (3.1–3.4 ms); runs on its own thread; off by default |
| Wi-Fi | 0.6–0.8 ms CPU per 5 s observation, elapsed p95 2.2 / 6.4 ms | call p95 **not met** (waiting on the driver); own thread; off by default |
| PSI | 1.8 µs per collection on the unsupported path (WSL tight loop) | normal path unmeasured on the boards (no PSI there); off by default |
| Probe | 0.3–0.7 ms loopback connect | real targets not approved: unmeasured; off by default |
| History | ≤ 3.7 MiB at its bound | integrated run within 2.0 %; off by default |

## Verified and not verified

Verified: full `pytest` and the web harness on every branch, CI on Python 3.9 and 3.13 (push and
pull_request) for every PR and this branch; Orin Nano and Raspberry Pi 4 natively on loopback test ports
(functional checks of every feature; per-feature cost; the integrated runs above); the web page in a real
browser (Chromium headless shell, 1280 px and 390 px) for #33's panels. Each device run left the boards'
own services (`e1bc82a`) untouched, compared by state records before and after (see the performance
reports for which runs have both). The integrated page with storage, the probe (to loopback) and history on
was also checked in that browser on WSL at 1280 px and 390 px; that check found a filesystem with 45 bind
mounts making the Storage panel and the `STORAGE` line unreadable, fixed in #34 (`efc6e59`: the first mount
point and "+N more").

Not verified: a container deployment of any new feature (the scope differences are documented, not run);
systemd installation of this branch; WSL for the low-frequency groups; PSI's normal path and the probe's
real targets on the boards; the Wi-Fi and pressure panels in a real browser (WSL has neither; harness
only); history filled to its retention on a board.

## Upgrade and rollout (for after approval; not done)

New installs get the defaults above. An existing install keeps its INI: Network and Disk I/O turn on
unless its INI says `enabled = no`; everything else stays off until enabled.

For each device, at a fixed merged SHA (the procedure used for earlier rollouts):

1. Record the running state: SHA, container id and image (Orin) or PID and start time (Raspberry Pi), INI,
   CLI, health.
2. Keep rollback material: tag the running image `platmon:rollback-<old sha>`, and copy the compose files,
   INI, CLI, container inspect output, ROLLBACK.md and SHA256SUMS to `~/platmon-rollback-<old sha>-<time>/`.
3. Build the candidate from `git archive <sha>` locally (`--provenance=false`); never pull or push images.
4. Smoke-test the candidate under its own compose project on `127.0.0.1:19797`: healthy, `/api/stats` 200
   with `network` and `disk_io`, source ids equal to the running service, then remove it.
5. Switch: check out the SHA, tag the candidate as `platmon:local`, recreate only the platmon service;
   on the Raspberry Pi, fast-forward its checkout and restart the process the same way it was started.
6. After: health, `/api/status` `ready`, CPU of the service compared with the integrated numbers above.
   Roll back (ROLLBACK.md) on a failed health check, a non-ready status for more than a minute, or CPU
   well above 2 % of one core.

Rolled out on 2026-10-09: #31 (`8525942`) on the Orin (14:09 KST, container) and the Raspberry Pi
(14:20 KST, native process), with this procedure ([development/remaining-work.md](development/remaining-work.md)).
#32–#38 are merged but not rolled out.

## Raw data

On each device: `~/platmon-rc-c2752c1/` (`run-1-default.json` … `run-4-default.json`, `ops-before.txt`,
`ops-after.txt`), plus the per-feature directories listed in the performance reports.

| board | run-1 default | run-2 all | run-3 all | run-4 default |
| --- | --- | --- | --- | --- |
| orin | `9f48f3c5…` | `09dd3239…` | `b92c63e7…` | `5ba67ce9…` |
| rpi4 | `088ae0e2…` | `c5763765…` | `dffe1d52…` | `0b58d724…` |
