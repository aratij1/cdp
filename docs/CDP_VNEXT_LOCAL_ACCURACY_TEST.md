# Local Accuracy Test — Cached Fixed-Family Baseline

Test date: 2026-08-21  
Authority: **BASELINE ONLY — NOT A vNEXT PRODUCTION CLAIM**

The repository evaluator was run with `evaluation_data/ground_truth.json` and cached
`evaluation_data/predictions_fixed_family.json`. Documents are deterministically split; ground truth
is joined only by the evaluator and is not supplied to inference.

| Slice | Documents | Fields | Normalized accuracy | Critical false-accept rate | Perfect claim rate | STP rate |
|---|---:|---:|---:|---:|---:|---:|
| Holdout | 5 | 61 | 78.6885% | 0% | 0% | 0% |
| Validation | 5 | 61 | 68.8525% | 0% | 20% | 20% |
| All splits | 30 | 366 | 71.0383% | 0% | 3.3333% | 3.3333% |

Artifacts are in `evaluation_results/vnext_local_holdout_baseline`,
`evaluation_results/vnext_local_validation_baseline`, and `evaluation_results/vnext_local_all_baseline`.

This run re-evaluates cached legacy predictions. It does not execute the newly added RapidOCR and
reconciliation path. RapidOCR, PaddleOCR, and Tesseract Python runtimes are not installed in the
current environment, so a fresh vNext OCR benchmark remains blocked. The five-document holdout is
also too small for a production generalization or critical-safety claim.
