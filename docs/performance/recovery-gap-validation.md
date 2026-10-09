# Recovery-gap correction validation (2026-10-09)

## Reproduction and scoped correction

Success, one failed core attempt, then success produced `[1001, 1003]` in history rather than
`[1001, null, 1003]`. The elapsed gap was shorter than the long-gap heuristic. Sampler's consecutive
failure count was reset before the next publication, so History could not identify this recovery.

#42 `00781fda6667234e088aa14107786be9e0a88532` carries one internal `gap_before` hint on the next
successful record. History adds a null break when a prior series exists, and the next uninterrupted
success adds no extra break. Failed attempts still publish no measured sample. Public stats/status
schemas, defaults, workers, collection calls and history bounds are unchanged. Focused tests: 50
passed; full component tests: 662 passed / 3 skipped. The regression failed before the correction.

## Predeclared corrected-runtime round

The previous single 60-minute round is kept as a baseline, including its 1830 s retention.
This additional round is justified by the reproduced correctness defect, not an optimization retry.
Do not overlap board runs. After the baseline runner finishes, archive the corrected integration
commit and hashes into a new directory `~/platmon-recovery-rc-<sha>/` on each board.

- One round, at most 60 minutes per board. No further automatic repeat or budget increase.
- Same ABBAABBA, 30 s warmup + 120 s/window, actual 1 s stats / 10 s optional API policy;
  default Network/Disk versus supported optional groups with own-loopback TCP only.
- Same 30 s warmup + 1800 s retention measurement, retention 600 s. Compare post-fill RSS/PSS
  across two additional 600 s periods, report slopes and point/identity bounds, no indefinite claim.
- Same default whole-process CPU <=2%, zero recorded failures/drops/fallbacks and no observed
  overruns. Explicitly retain sampled-timing coverage limits; do not relabel missing observations
  as collection failures or claim complete per-attempt timing.
- The unchanged Storage/Wi-Fi readers reuse their actual-cadence cost results and default-off
  p95 failure disclosure. The unchanged frontend reuses the final 661 s browser soak and fixtures.
- Only after native measurement, run the prepared Orin compose check with a unique project/image,
  loopback port, non-root/read-only/cap-drop/no-new-privileges configuration; preserve the image.
- Preserve raw, all before/after operational identities, original production `8525942` and rollback
  material. Never modify production units, power/governors, kernel, remote probe targets or registries.

Corrected integration full tests and Python 3.9/3.13 CI must pass before component merge. The measured
SHA and result hashes will be recorded below after completion. PSI and actual systemd privilege limits
remain disclosed. The earlier CPU/memory results are not mislabeled as measurements of this correction.

## Results

Pending the declared run; #42 and the aggregate stay Draft.
