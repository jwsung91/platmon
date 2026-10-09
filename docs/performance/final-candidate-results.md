# Candidate baseline results before recovery-gap correction (2026-10-09)

A later targeted test reproduced a short core failure being connected across the graph. The
correction in #42 at `00781fd` changes Sampler/History, so these CPU results are now a baseline,
not the corrected-runtime gate. Retention raw is preserved. Corrected-runtime validation follows
the separately bounded [recovery-gap plan](recovery-gap-validation.md). The unchanged frontend
reuses the browser evidence below.

Measured commit: `30d377a9b7cd470d655367398dab39c3b1f5313a` on both boards, archived before
measurement. [Predeclared plan](final-candidate-plan.md), 60 minutes maximum per board.
Source tar SHA-256: `6c77a153f5a80c084af5668aa198548337b0d855e30a8646120d3a78ff73df97`.
Service benchmark SHA-256: `159e5ce3da350cb5f99c4a70de140437b67c8d6c876aba545f16cc7256b38b2a`.
Initial merge/documentation commits preserved this runtime and benchmark byte-for-byte;
the later recovery-gap correction is a distinct measured runtime.

## Whole-service CPU

Two ABBA blocks per board, each window 30 s warmup + 120 s measured; core and stats client 1 s,
observations/history client 10 s. A: default Network + Disk; B: additionally Storage 30 s, Wi-Fi 5 s,
600 s History and own-loopback TCP 10 s. PSI disabled (unsupported kernels). All worker CPU is
included in the service process user+system time; the client is separate.

| Board | Default CPU %, run order | All-on CPU %, run order | Block deltas, pp |
| --- | --- | --- | --- |
| orin | 1.600, 1.600, 1.595, 1.608 | 1.808, 1.802, 1.775, 1.850 | +0.205, +0.211 |
| pi | 1.617, 1.600, 1.567, 1.612 | 1.892, 1.925, 1.883, 1.959 | +0.300, +0.332 |

Every default window passes the <=2% one-core target. All-on windows also remain below 2%, within
the restricted support scope above. No threshold was increased. The independent Storage/Wi-Fi
elapsed call p95 failures (3.212/3.223 ms and 3.365/7.871 ms, Orin/Pi) remain; those features stay off.

All 16 services exited 0, without forced kill, residual PID or listener. Every requested HTTP
response had its expected status (disabled history is expected 404), with zero freshness fallback,
core diagnostic errors, logged collection failures or logged stale-result drops. Observed sample
durations stayed below 23.564 ms (Orin) / 15.161 ms (Pi), with no observed overrun.
One Orin window's 1 s client missed two intermediate published sequence numbers; the other 15
windows have no missing sequence within their observed ranges. This is sampled duration coverage,
not proof of every attempt's timing or scheduler delay. It is not reported as a collection failure.
Each process used a distinct instance ID. Within each run, status, stats, observations and enabled
history agreed on the instance; no prior instance survived the successive restarts.

The earlier `e919baf` matrix is historical because another validation overlapped its beginning.
These windows ran without that competing benchmark. Original evidence is retained unchanged.

## Final browser

Chromium 153.0.8010.12: real 1280/390 px fixture checks for escaping, gaps, stale values, 503,
5 s timeout, synthetic tab-return and bounded history passed. The final live page ran 661.504 s:
661 stats, 64 observations and 64 history requests; no JS errors; 305 live DOM nodes throughout.
CDP renderer task time was 6.111 s and final JS heap 3,223,008 bytes. These are browser measurements,
not daemon CPU/RSS. The local service exited 0 and port closed. Its WSL file-bind capacity remained
null/io_error as documented; no unsupported sensor path is presented as tested hardware.

## Retention and deployment forms

The single 1830 s retention run is in progress on both boards. Final post-fill RSS/PSS, identity,
point bounds and operational comparison are pending. Orin's isolated compose check follows the
measurements, so a build cannot contaminate them. Pi `systemd-analyze verify platmon.service` exits
0; actual DynamicUser execution is unavailable because administrator authentication is required.

## Evidence

Raw windows, source, INIs, before/after state, input hashes and scripts remain in
`~/platmon-final-rc-30d377a/` on each board and private `.validation/final-rc-evidence/` locally.
The final result manifest will be recorded when the bounded run completes. Production remains
`8525942`; no deployment, release, tag, registry push or old-image/raw cleanup is part of this run.

Executed window command (the INI alone selects A/B, in ABBAABBA order):

```bash
python3 benchmarks/service_cpu.py --ini default.ini --port 19869 --page \
  --source-sha 30d377a9b7cd470d655367398dab39c3b1f5313a \
  --warmup 30 --measure 120 --out run-1-default.json
```

The separate retention command uses `--ini all.ini --warmup 30 --measure 1800 --out retention.json`.
The preserved `run_final.py` supplies the remaining identical arguments, refuses an exhausted
budget, checks results and snapshots production before/after. These commands target only the
isolated archived directory and loopback port, never the production checkout.
