# Phase 8.10B OCR Experiment 1 — reverted

## Hypothesis

Names dominate the primary OCR failure set (63 of 89 failures), primarily through word segmentation. Applying the already configured `NAME_STROKE_V2` preparation to the existing unresolved-name regional RapidOCR read may recover names without adding an engine, route, crop, or policy change.

## One treatment

Only the existing regional RapidOCR call for an invalid name candidate received `NAME_STROKE_V2` preprocessing. Localization, crop coordinates, candidate validity, evidence policy, route registry, claim policy, UB service lines, HITL, and STP were frozen.

## Gate result

| Metric | Frozen baseline | Treatment |
|---|---:|---:|
| Primary observation OCR on usable regions | 301/390 (77.18%) | 301/390 (77.18%) |
| Final correct on usable regions | 372/390 (95.38%) | 370/390 (94.87%) |
| Overall accuracy | 89.05% | 88.57% |
| CMS1500 accuracy | 88.74% | 87.45% |
| UB04 accuracy | 89.42% | 89.95% |
| Critical accuracy | 91.67% | 91.37% |
| Incremental correct regional resolutions | 24 | 22 |
| Canonical accepted precision | 96% | Not evaluated after hard extraction regression |
| Canonical critical false accepts | 1 | Not evaluated after hard extraction regression |
| Worst source P95 | 10.127 s | 9.300 s |
| Cloud cost/page | $0 | $0 |

Decision: **REVERT**. Accuracy and critical accuracy regressed, so the treatment was removed in full before downstream canonical acceptance promotion could be considered. No OCR promotion report was created and the frozen OCR/runtime behavior remains unchanged.
