# CDP Raw Accuracy Recovery Report

> In progress. All current figures are synthetic-only.

- Frozen baseline: 58.83% (353/600)
- Final raw accuracy: 99.00% (594/600)
- CMS: 98.33%
- UB-04: 99.44%
- Critical accuracy: 99.05%
- Crop correctness: 100.00%
- OCR accuracy conditional on correct crop: 99.00%
- Normalization regressions: 0
- Registration errors: 0
- OCR errors: 6
- UB row errors: not measurable; the fixture has no service lines
- Safe automation coverage: 7.83%
- HITL: 92.17%
- False accepts: 0
- Mean latency: 352.62 ms
- P95 latency: 750.00 ms

## Top errors before

`insured_id_number` 60; `federal_tax_no` 60; `provider_npi` 44; `patient_dob` 38; `patient_name` 43.

## Top errors after

`patient_name` 3, `federal_tax_no` 2, `insured_id_number` 1

## Next recommended work

Build an untouched production-representative holdout and retain the six residual correct-crop OCR errors for field-specific recovery. Raw accuracy now permits cautious evidence/HITL optimization without lowering acceptance thresholds.
