# CDP Phase 8.10 Failure Decomposition

## Fixed-field attribution

The frozen replay has 46 incorrect fields out of 420. Every incorrect field has exactly one primary layer; 46/46 (100%) are meaningfully attributed.

| Primary layer | Count | Share of fixed-field errors |
| --- | ---: | ---: |
| OCR empty | 19 | 41.30% |
| OCR character error | 16 | 34.78% |
| Field localization | 7 | 15.22% |
| Crop / under-crop | 2 | 4.35% |
| Parser / token selection / candidate ranking | 1 | 2.17% |
| Normalization | 1 | 2.17% |
| Classification | 0 | Not exercised; family is injected |
| Registration | 0 | Not independently exercised by this replay |
| Ownership | 0 | No separate primary label emitted |
| Evidence | 0 | Evidence affects review, not extracted-value accuracy |
| Decision | 0 | No accepted wrong field; accepted precision is 100% |
| Other | 0 | 0% |

OCR empty plus OCR character error accounts for 35/46, or 76.09%, and is the dominant fixed-field component.

## UB service-line attribution

This uses a separate denominator and must not be added to the 46 fixed-field errors. All 89 truth rows were detected. Twenty-eight rows were not exact, and all 28 are attributed to UB column assignment/reconstruction: Source A 6, Source B 9, Source C 13. Exact-row accuracy is 68.54%; cell accuracy is 85.02%.

## Conditional accuracy

- Production-usable localization: 369/420 = 87.86%.
- OCR given a region marked correct by the extraction record: 301/390 = 77.18%.
- Final normalization/parser correctness given correct OCR: 300/301 = 99.67%.

There is an evaluation-boundary inconsistency: the localization scorer reports 411/420 value containment after its Source-C scoring transform, while the extraction records mark 390/420 `expected_value_in_region`. Therefore the OCR conditional denominator is reproducible but is not aligned to the production-usable localization denominator. It must not be presented as a fully coherent stage funnel until evaluation parity is fixed.

## Single next bottleneck

The selected bottleneck is **regional RapidOCR recognition on correctly localized fixed-field crops**. OCR empty plus character errors account for 35/46 errors (76.09%); frequency is high, the same failure appears across sources and form families, and it can be isolated without touching decisions. Evaluation policy parity remains a P0 measurement defect and must be made identical by run configuration before this experiment, but it is not counted as a product-accuracy error layer.

Exactly one future implementation unit is authorized by this reset: replace the current generic regional crop preparation inside the existing RapidOCR regional adapter with the already-defined field-profile preparation selected from `config/ocr_preprocessing_phase8_10.yaml`. The engine, model, number of OCR calls, ROI, crop bounds, candidate selection, normalization, evidence, HITL, STP, and routing remain frozen.

Experiment contract:

- Hypothesis: field-profile preparation in the one permitted regional RapidOCR call reduces OCR-empty and OCR-character failures without increasing false accepts.
- Component: the existing regional RapidOCR crop-preparation adapter only.
- Change: `REGIONAL_DEFAULT` preparation becomes the configured field profile; no second OCR call is added.
- Frozen dataset/baseline: the hashes and commit in `CDP_ARCHITECTURE_RESET_BASELINE.md`.
- Precondition: evaluator uses runtime route/policy identities and fails if they differ.
- Primary gate: at least 20% relative reduction in the 35 OCR-attributed errors, with no increase in the 11 non-OCR fixed-field errors.
- Safety gate: accepted precision remains 100%, critical false accepts remain 0, cloud calls remain 0, secondary invocation rate does not increase, and P95 does not regress by more than 5%.
- Rollback: revert the single crop-preparation adapter change if any safety gate fails; classify an underpowered result as `NEEDS_MORE_DATA`.
