# CDP Phase 7A.14 Registration Failure Pareto

Tuning-only replay: 132 attempts, 0 successes, 132 failures. Classified failure rate: 100.00%.

| Primary cause | Count |
|---|---:|
| TEMPLATE_LINEAGE_MISMATCH | 64 |
| RANSAC_INLIER_FAILURE | 54 |
| INVALID_TRANSFORMED_CORNERS | 9 |
| LOWE_FILTER_COLLAPSE | 5 |

The compatibility precheck avoided SIFT on 62 incompatible pages. Full per-attempt evidence is in `evaluation_results/phase7a14/registration_forensics.json`.
