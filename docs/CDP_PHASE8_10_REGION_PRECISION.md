# CDP Phase 8.10 — Region Precision

## Decision

`NEEDS_MORE_DATA`

The Phase 8.9 baseline was reproduced and frozen at commit `1ed19cd0015aa6ef72afc13a99b39d81e951eb17`. The locked holdout was not accessed. Runtime truth access remains prohibited.

## Measured validation result

| Metric | Result | Target | Gate |
|---|---:|---:|---|
| Expected value in region | 97.86% | ≥95% | PASS |
| Production-usable localization | 87.86% | ≥95% | FAIL |
| Critical production-usable localization | 88.69% | ≥97% | FAIL |
| Over-crop rate | 6.43% | ≤20% | PASS |
| Wrong-crop recall | 45.10% | ≥90% | FAIL |
| Wrong-crop precision | 100.00% | ≥90% | PASS |

`PRODUCTION_USABLE_LOCALIZATION` requires containment, a field-aware excess-area bound, a non-empty region, no label contamination, no ambiguity, and `REGION_OWNED`. It does not count an over-crop as success.

The dominant residual is ownership uncertainty, not missing value containment. The V2 firewall rejects `UNKNOWN`, `REGION_AMBIGUOUS`, `MULTI_FIELD_CROP`, `LABEL_CONTAMINATED`, and explicit wrong-neighbor outcomes for critical processing. This preserves fail-closed behavior but leaves the localization target unmet.

## Architecture changes

- Candidate generation now follows only declared field relationships and persists relationship ID, type, score, and geometry.
- Page-percentage padding was removed. Bounds use character height, observed span width, declared neighbors, and datatype-specific limits.
- Type compatibility is separate from downstream value validity; NPI checksum and date plausibility do not authorize localization.
- `FieldRegionConflictDetector` supplies explicit ownership outcomes.
- Registered-template polygons are transformed from canonical to page coordinates with translation, scale, rotation, perspective, crop clipping, convexity, and degeneracy checks.
- Source-C evaluation boxes are mapped through the dataset's declared affine transform. This correction is evaluation-only and never enters runtime extraction.

Detailed records are in `evaluation_results/phase8_10/localization_records.jsonl`; the OCR-free benchmark is in `evaluation_results/phase8_10/localization_only/`.
