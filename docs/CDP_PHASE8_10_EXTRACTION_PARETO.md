# CDP Phase 8.10 — Extraction Pareto

## Accuracy

| Metric | Result | Target | Gate |
|---|---:|---:|---|
| Overall final field accuracy | 89.05% | ≥90% | FAIL |
| CMS1500 final field accuracy | 88.74% | ≥90% | FAIL |
| UB04 final field accuracy | 89.42% | ≥90% | FAIL |
| Critical-field accuracy | 91.67% | ≥95% | FAIL |
| Accepted-field precision | 100.00% | ≥99.5% | PASS |
| Critical false accepts | 0 | 0 | PASS |

## Failure Pareto

| Failure layer | Count |
|---|---:|
| OCR empty | 19 |
| OCR character error | 16 |
| Localization wrong | 7 |
| Under-crop | 2 |
| Candidate ranking | 1 |
| Normalization | 1 |

OCR-empty cases are mostly firewall-rejected ambiguous or multi-field regions. Relaxing that rejection would improve apparent accuracy at the expense of false-accept safety, so it was not done.

Selective regional OCR ran for 67 of 420 validation fields (15.95%) and added 24 correct resolutions at $0 cloud cost. Per-invocation latency was not persisted, so its incremental latency contribution is explicitly `NOT_MEASURED` rather than inferred.

UB service-line row detection recall is 100.00%; exact-row accuracy is 68.54% and column-cell accuracy is 85.02%. The residual service-line layer is column assignment, especially on Source C.

Detailed field records are in `evaluation_results/phase8_10/extraction_records.jsonl` and `extraction_failure_records.json`.
