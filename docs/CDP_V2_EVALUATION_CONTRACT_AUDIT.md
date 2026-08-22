# CDP V2 Evaluation Contract Audit

All 4,281 frozen comparisons were audited using explicit crosswalk version
`v2.0`. No OCR, routing, normalization, or evidence behavior was changed.

| Measure | Result |
|---|---:|
| Original exact accuracy | 0.234% |
| Canonicalized accuracy | 0.280% |
| Supported/applicable canonical accuracy | 0.356% |
| Meaningfully classified comparisons | 100% |

| Classification | Count |
|---|---:|
| Route not executed | 2,160 |
| True extraction error | 946 |
| Unsupported field | 876 |
| Empty prediction | 249 |
| Field-name mismatch | 11 |
| Name-order mismatch | 2 |
| Field not applicable to extraction | 27 |
| Exact match | 10 |

Formatting and name ordering explain only two additional matches. The failed
score is therefore not primarily an evaluator normalization defect. Routing
and route-to-extractor compatibility dominate, followed by actual extraction
errors and unsupported schema coverage.

Detailed records are in
`evaluation_results/PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED/comparison_audit.json`.
