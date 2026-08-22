# CDP vNext Accuracy Qualification

Qualification date: 2026-08-21  
Status: **NOT TESTED / NOT QUALIFIED**

No defensible end-to-end accuracy number exists yet for CDP vNext. The repository contains two
older sample results, but neither is production authority for this candidate:

| Evidence | Scope | Result | Permitted interpretation |
|---|---:|---:|---|
| `current_v2_router` | 214 visible fields | 89.2523% extraction; 99.0654% page | Frozen v2 baseline only |
| `current_sample_100` | 239 fields | 99.5816% evidence-derived; 100% after one user confirmation | Sample benchmark only; explicitly `production_authority: false` |
| CDP vNext governed holdout | Not run | NOT TESTED | No accuracy claim permitted |

Both historical artifacts report zero critical false accepts, but their sample sizes are too small
to establish a production safety bound. Promotion requires a locked, representative and independently
labeled holdout, per-family/per-field results, confidence intervals, critical false-accept counts,
review rate, leakage checks, and a signed evaluation manifest.

The current answer to “what is the accuracy?” is therefore: **vNext accuracy is unknown**. The best
available historical automated baseline is 89.2523%, not a vNext production claim.

## Local reproducibility run

On 2026-08-21, the standard evaluator re-scored the cached fixed-family prediction artifact. The
five-document, 61-field holdout measured **78.6885% normalized accuracy**, zero observed critical
false accepts, and 0% STP. Across all 30 documents and 366 fields it measured **71.0383%**. These
figures use cached legacy predictions and therefore establish evaluator reproducibility, not vNext
model accuracy. See `CDP_VNEXT_LOCAL_ACCURACY_TEST.md`.

## Fresh local OCR run

After installing the pinned OCR runtimes, fresh PaddleOCR/Tesseract inference on the existing field
crops measured **68.8525%** on the five-document holdout and **67.2131%** across all 30 documents.
The full set produced a **3.8462% critical false-accept rate**, so promotion fails. RapidOCR passed a
live smoke test but is not invoked by the legacy atomic benchmark driver. See
`CDP_VNEXT_FRESH_OCR_TEST.md` for scope and limitations.

## Accuracy-improvement implementation

The RapidOCR-first, independently reconciled development run subsequently reached **77.0492%** on
the existing five-document split and **72.1311%** across all 30 documents after unstructured-family
routing. It produced zero observed critical false accepts and zero total false accepts, while routing
uncertain evidence to review. These are development results because existing crops were reused and
the splits were inspected during diagnosis. See `CDP_VNEXT_ACCURACY_IMPROVEMENT_REPORT.md`.
