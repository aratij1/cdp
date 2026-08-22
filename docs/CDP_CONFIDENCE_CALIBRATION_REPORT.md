# CDP confidence calibration report

Status date: 2026-08-22. Calibration is implemented and versioned; current learned field models remain `SHADOW_ONLY` pending untouched-holdout qualification.

## Implementation

- Supports versioned isotonic and Platt calibration with bounded probabilities.
- Resolves models by engine/field, engine wildcard, field wildcard, then global fallback.
- Captures engine confidences, agreement count, registration confidence, image quality, deterministic format validity, reference score, cross-field consistency, preprocessing profile, label contamination and correctness.
- Reports Brier score, expected calibration error, reliability curves, precision at threshold and acceptance rate.
- Rejects malformed or non-monotonic isotonic models.
- Reconciliation records the exact calibration model version used.

Raw OCR scores are not treated as independent proof for C2/C3 fields. Acceptance also requires the configured evidence policy and deterministic validation. The current address/name/other isotonic models in `config/calibration/field_models_v1.json` remain shadow-only because they were derived from development evidence.

## Baseline and decision

No new governed accuracy metrics were generated in this phase. Baseline remains 72.13% overall, 65.56% critical accuracy, zero measured false accepts, 0% STP and 76.67% review. Promotion decision: `NEEDS_MORE_DATA` until calibration is measured on a non-tuning split and then confirmed on the untouched holdout.
