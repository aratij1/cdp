# CDP Raw Accuracy Recovery Experiments

> All measurements below are from PHI-free synthetic data and are not production accuracy.

## Experiment 1 — Remove label/data ROI collisions

- Hypothesis: most baseline failures are synthetic labels or form rules rendered inside populated ROIs.
- Fields: insured ID, federal tax number, provider NPI, DOB, patient name.
- Files changed: `evaluation/generate_public_synthetic_claims.py`.
- Baseline field accuracy: insured ID 0%; federal tax 0%; provider NPI 26.67%; DOB 68.33%; name 64.17%.
- New field accuracy: insured ID 1.67%; federal tax 0%; provider NPI 100%; DOB 100%; name 97.50%.
- Error count: 247 → 123.
- Overall: 58.83% → 79.50%.
- CMS / UB-04: 74.17% / 83.06% after change.
- Baseline crop correctness: 59.17%; OCR given correct crop: 99.44%.
- False accepts: 0.
- Safe coverage / HITL: 8.00% / 92.00%.
- Mean / P95: 330.19 / 652.45 ms.
- Decision: **PROMOTE** as a benchmark-generation correction; no production OCR claim.

## Experiment 2 — Fit clipped synthetic values to tight ROIs

- Hypothesis: the 22-pixel UB-04 federal-tax ROI clips the fixed 24-pixel rendered font.
- Fields: federal tax number; all already-fitting fields remain on their frozen layout.
- Files changed: `evaluation/generate_public_synthetic_claims.py`.
- Baseline field accuracy: federal tax 0%.
- New field accuracy: federal tax 96.67%.
- Error count: 123 → 64.
- Overall: 79.50% → 89.33%.
- CMS / UB-04: 74.17% / 99.44%.
- Crop correctness / OCR given correct crop: 100% / 89.33% on corrected renderer contract.
- False accepts: 0.
- Safe coverage / HITL: 7.83% / 92.17%.
- Mean / P95: 350.86 / 699.04 ms.
- Decision: **PROMOTE** as a benchmark-generation correction; strong fields did not regress.

## Experiment 3 — Field-specific member-ID OCR route

- Hypothesis: Tesseract is the wrong recognizer for alphanumeric member IDs with repeated zeroes.
- Field: `insured_id_number`.
- Engine benchmark: RapidOCR 100% at 1,886.6 ms; PaddleOCR 98.33% at 361.5 ms; Tesseract 3.33% at 604.7 ms.
- Files changed: `evaluation/benchmark_synthetic_claims.py`, `evaluation/ocr_field_benchmark.py`.
- Baseline field accuracy: 1.67% on the corrected fixture.
- New field accuracy: 98.33% with PaddleOCR.
- Error count: 64 → 6.
- Overall: 89.33% → 99.00%.
- CMS / UB-04: 98.33% / 99.44%.
- Critical accuracy: 99.05%.
- Crop correctness / OCR given correct crop: 100% / 99.00%.
- False accepts: 0.
- Safe coverage / HITL: 7.83% / 92.17%.
- Mean / P95: 352.62 / 750.00 ms.
- Decision: **NEEDS_MORE_DATA** for production promotion; retain as a configurable route pending an untouched real holdout.
