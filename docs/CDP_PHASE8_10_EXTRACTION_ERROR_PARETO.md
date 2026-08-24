# CDP Phase 8.10 — Extraction Error Pareto

The taxonomy assigns exactly one primary category to each of 60 incorrect
validation fields, with optional diagnostic secondary reasons.

| Primary failure | Count |
| --- | ---: |
| OCR character error | 29 |
| Localization wrong | 14 |
| OCR word error | 9 |
| Under-crop | 4 |
| OCR empty | 2 |
| Candidate ranking error | 1 |
| Normalization error | 1 |

The evaluator also emits breakouts by document family, field, source,
criticality, engine, preprocessing profile, and localization strategy. OCR
character/word errors account for 63.33% of residual failures. Only one failure
is ranking-related, so adding more scoring complexity has low near-term value.

Artifacts: `extraction_failure_records.json/csv` and
`extraction_error_pareto.json/csv` under `evaluation_results/phase8_10/`.
