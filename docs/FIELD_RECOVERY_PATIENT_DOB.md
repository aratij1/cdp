# Field Recovery: `patient_dob`

> Synthetic benchmark result; not production accuracy.

- Frozen baseline: 82/120 (68.33%), 38 errors.
- Corrected label-safe fixture: 120/120 (100%).
- Error reduction: 38.
- Root cause: synthetic neighboring-label/box overlap in UB-04 crops.
- Production OCR change: none.

The existing date extractor was preserved. The measured recovery came from repairing the benchmark renderer.
