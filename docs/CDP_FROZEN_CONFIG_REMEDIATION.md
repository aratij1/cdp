# Frozen CMS-1500 Configuration Remediation

## Root cause

`extraction-v2` was frozen on 2026-07-30. Commit `a666571` on 2026-08-05 then lowered CMS-1500 and UB-04 critical thresholds to 0.80 and removed multiple rules without creating a new release manifest. The first hash failure masked the second. These were genuine unversioned policy mutations, not newline or serialization drift.

## Remediation

Both frozen paths were restored to their recorded pre-change safety policies. The later lowered variants are retained under `config/validation/history/` with `QUARANTINED_UNVERSIONED_CHANGE` status so the history is explicit and the runtime registry cannot load them accidentally. The frozen `extraction-v2` manifest was not edited.

Any future threshold change requires a new versioned validation file, independent holdout evidence, migration notes, and a new release manifest.
