# CDP Phase 6 — Confidence Calibration

## Decision

**NEEDS_MORE_DATA.** Platt and isotonic calibration are implemented and compared without training on holdout data. Address, name, and miscellaneous families have usable development estimates, but identifier, date, and clinical-code families lack enough examples. All generated models remain `SHADOW_ONLY`.

## Leakage controls

- Training uses only the 20-document `calibration` split.
- Model selection and reported metrics use only the 5-document `validation` split.
- All 5 existing `holdout` documents are excluded from feature records, fitting, model selection, and reported calibration metrics.
- The future untouched production holdout remains unavailable and must not be used for training.

## Implemented

- Auditable feature records covering document type, field/family, criticality, selected engine, RapidOCR/Paddle/Tesseract confidence, agreement count, registration confidence, image quality, format validity, reference score, cross-field consistency, preprocessing, label contamination, and correctness.
- Dependency-free Platt fitting and pool-adjacent-violators isotonic fitting.
- Brier score, Expected Calibration Error, reliability bins, precision at the 0.99 auto-accept threshold, and acceptance rate at that threshold.
- Per-family comparison with deterministic selection and a Platt tie preference.
- Strict, versioned JSON registry loading for inference.
- Generated models are not loaded automatically into production reconciliation.

## Validation results

| Family | Train | Validation | Selected | Raw Brier | Calibrated Brier | Raw ECE | Calibrated ECE |
|---|---:|---:|---|---:|---:|---:|---:|
| Address | 138 | 34 | Isotonic | 0.3385 | 0.2171 | 0.3561 | 0.1821 |
| Name | 40 | 10 | Isotonic | 0.1095 | 0.0750 | 0.1312 | 0.1500 |
| Other | 32 | 8 | Isotonic | 0.1555 | 0.1155 | 0.1916 | 0.1652 |

Clinical-code, date, and identifier families each have only 4 calibration records and 1 validation record, so no model was produced for them.

The selected models showed 100% observed precision at probability 0.99 in their tiny validation acceptance subsets: address accepted 3 records, name 2, and other 6. These counts are far too small for a production precision claim.

## Safety and impact

- Focused and architecture tests: 39 passed.
- Full regression suite: 583 passed, 5 skipped, and the one previously known frozen-manifest hash failure.
- Field-specific evidence policies remain mandatory after calibration. A calibrated probability cannot replace OCR independence, checksum, authoritative reference, code-set, or financial reconciliation evidence.
- Safe review reduction: 0 / 262 = 0% because shadow probabilities were not used to change dispositions.
- False accepts introduced: 0.
- Accuracy and review-rate deltas: 0 percentage points.
- Training and inference add no cloud cost; model inference is constant-time local arithmetic.

## Next gate

Collect substantially more labeled calibration and validation examples for critical identifiers, dates, and codes; require meaningful support above the 0.99 threshold; and validate calibration again on the future untouched holdout. The next ordered implementation phase is adaptive escalation routing.
