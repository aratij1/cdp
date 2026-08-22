# CDP Phase 2 Evidence Optimization Report

## Outcome

The measured synthetic candidate frontier reaches the requested field-level target without changing the frozen extractor:

| Metric | Frozen decision baseline | Measured E2 candidate |
|---|---:|---:|
| Raw extraction accuracy | 99.00% (594/600) | 99.00% (594/600) |
| Safe accepted coverage | 0.00% | 75.83% (455/600) |
| Estimated final field HITL | 100.00% | 24.17% (145/600) |
| Estimated critical-field HITL | 100.00% | 24.17% |
| Claim HITL | 100.00% | 65.83% (79/120) |
| Claim STP | 0.00% | 34.17% (41/120) |
| False accepts | 0 | 0 |
| Critical false accepts | 0 | 0 |
| Estimated mean latency | 352.62 ms | 967.77 ms |
| Estimated P95 latency | 750.00 ms | 2571.95 ms |
| Additional local OCR calls | 0 | 600 |

These are corrected synthetic development results, not production accuracy or a production automation claim.

## Why the recomputed baseline is lower than the prior 7.83%

The earlier 47 accepted values were backed by same-engine NPI retry behavior. Under the standardized independence rule, a Tesseract preprocessing retry is still the Tesseract family and cannot create E2. The canonical replay therefore starts at zero safe acceptances, with 549 fields routed for more evidence and 51 already terminal-review candidates.

## Evidence-gap result

All 594 correct-but-unaccepted fields received a meaningful cause:

- 515 (86.70%) have a measured agreeing independent candidate that is not part of the frozen production candidate set: `EVIDENCE_NOT_PROPAGATED`.
- 79 (13.30%) have a measured confirmation contradiction and remain unresolved.

No confidence threshold was reduced. E1 alone remains insufficient for C2/C3.

## Field-level candidate results

| Field | Accepted | Total | False accepts | Mean confirmation latency |
|---|---:|---:|---:|---:|
| `patient_name` | 84 | 120 | 0 | 931.2 ms |
| `patient_dob` | 105 | 120 | 0 | 215.6 ms |
| `total_charge` | 59 | 60 | 0 | 272.0 ms |
| `insured_id_number` | 59 | 60 | 0 | 1886.6 ms |
| `provider_npi` | 60 | 60 | 0 | 236.2 ms |
| `type_of_bill` | 45 | 60 | 0 | 446.3 ms |
| `principal_diagnosis` | 0 | 60 | 0 | 490.2 ms |
| `federal_tax_no` | 43 | 60 | 0 | 526.7 ms |

The synthetic `principal_diagnosis=Z0000` fixture is not accepted by the deterministic ICD validator. This is correctly treated as missing/failed E4 rather than weakening the validator.

## Promotion status

`insured_id_number` retains the benchmark-selected Paddle primary and Rapid confirmation; Tesseract is explicitly excluded for that field. Newly measured non-member Paddle confirmation routes are stored externally but marked `SYNTHETIC_CANDIDATE_NOT_PRODUCTION_APPROVED` and `runtime_enabled: false`. Production promotion requires an independent holdout with zero critical false accepts and latency/capacity approval.

The detailed artifacts are:

- `evaluation_results/evidence_optimization/extraction_baseline_v1/manifest.json`
- `evaluation_results/evidence_optimization/baseline/metrics.json`
- `evaluation_results/evidence_optimization/optimized/metrics.json`
- `evaluation_results/evidence_optimization/frontier.json`
- `docs/CDP_EVIDENCE_GAP_PARETO.md`
- `docs/CDP_EVIDENCE_COUNTERFACTUAL.md`
- `docs/CDP_SAFE_COVERAGE_FRONTIER.md`
