# CDP vNext Accuracy Improvement Report

Run date: 2026-08-21  
Decision: **DEVELOPMENT IMPROVEMENT — PRODUCTION PROMOTION STILL BLOCKED**

## Implemented

- RapidOCR/ONNX is now the primary candidate family in the atomic benchmark.
- Low-height crops receive field-aware contrast normalization and 2x/3x upscaling.
- Tesseract uses field-specific PSM/character constraints plus an independent sparse-text pass.
- Candidate selection prefers agreement across RapidOCR, PaddleOCR, and Tesseract families.
- Critical person names always route to review without governed identity evidence.
- Printed form vocabulary is rejected as a person name.
- Address suffix ordering and evidence-preserving SELF projections were corrected.
- Checkbox interiors use calibrated geometry instead of printed labels/borders.
- Missing clean template reference images now fail fresh crop generation with an actionable error.
- Unstructured family routing was replayed; three of seven documents routed, four remained review-only.

## Measured comparison

| Metric | Fresh pre-change | Improved | Change |
|---|---:|---:|---:|
| Development holdout accuracy | 68.8525% | 77.0492% | +8.1967 pp |
| All-sample accuracy | 67.2131% | 72.1311% | +4.9180 pp |
| Critical-field accuracy | 57.7778% | 65.5556% | +7.7778 pp |
| Critical false-accept rate | 3.8462% | 0% | -3.8462 pp |
| Overall false-accept rate | 11.6667% | 0% | -11.6667 pp |
| Perfect-claim rate | 3.3333% | 20% | +16.6667 pp |

Safety deliberately trades automation for review: STP is 0% and review coverage is high because
uncalibrated names and single-family evidence fail closed.

## Limits

This is a development-set result, not an independent accuracy claim. Existing crops were reused
because operator-approved blank template references are absent. Unstructured page OCR came from the
existing inventory. During diagnostics the existing split results were inspected, so a new untouched
holdout is required before promotion. The dataset has only 30 documents and 366 fields.
