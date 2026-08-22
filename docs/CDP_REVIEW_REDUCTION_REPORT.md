# CDP Review Reduction Report

Status: **PHASE 1 ANALYTICS — NEEDS MORE DATA**

The baseline is reproducible at 72.1311% overall accuracy, 77.0492% on the existing
development split, zero observed false accepts, 0% STP, and 76.6667% claim-level review.
Review-reason percentages below are multi-label and may sum above 100%.

## Safe review reduction KPI

- Previous review fields: 262
- Review cases removed: 0
- Correctly automated former reviews: 0
- Safe review reduction: 0.00%
- False accepts introduced: 0
- Additional compute/cloud cost and latency: NOT MEASURED in this analytics-only phase

## Top 10 review reasons

| Reason | Fields | % of reviews | Automation strategy |
|---|---:|---:|---|
| OCR_DISAGREEMENT | 201 | 76.72% | field-specific preprocessing and independent reconciliation |
| NO_EVIDENCE | 171 | 65.27% | expanded crop then adaptive escalation |
| ADDRESS_AMBIGUOUS | 154 | 58.78% | component parsing and address reference |
| EMPTY_CROP | 137 | 52.29% | registration and expanded-crop retry |
| LOW_REGISTRATION_CONFIDENCE | 122 | 46.56% | canonical template registration |
| LOW_OCR_CONFIDENCE | 118 | 45.04% | expanded crop or constrained OCR |
| INVALID_FORMAT | 91 | 34.73% | deterministic parser/validator |
| UNSTRUCTURED_DOCUMENT | 91 | 34.73% | family routing and anchor-relative extraction |
| MULTIPLE_PLAUSIBLE_VALUES | 85 | 32.44% | reference lookup or selective resolver |
| CRITICAL_NAME_UNVERIFIED | 60 | 22.90% | authoritative member identity match |

## Top 20 review-heavy fields

| Field | Review fields |
|---|---:|
| patient_last | 30 |
| patient_first | 30 |
| patient_addr2 | 24 |
| insured_addr2 | 24 |
| patient_addr1 | 21 |
| patient_city | 20 |
| patient_state | 20 |
| patient_zip | 20 |
| insured_addr1 | 16 |
| insured_city | 15 |
| insured_state | 14 |
| insured_zip | 14 |
| rel_code | 7 |
| type_of_bill | 6 |
| patient_sex | 1 |

## Review-heavy document families

| Family | Review fields |
|---|---:|
| CMS1500 | 152 |
| UNSTRUCTURED | 91 |
| UB04 | 19 |

## Evidence identity

- `evaluation_data\ground_truth.json`: `f7f91d5e912a8ba5806d3d29e5a40cecd248d14cc5a9ee694c433e6341afc954`
- `evaluation_results\vnext_accuracy_improvement\predictions_with_unstructured.json`: `2ad18b2597a2857d1aad8c450c45b3c78b26583a9c56440bab2afc5776d82c67`

## Decision

**NEEDS MORE DATA.** Analytics are complete; no acceptance policy changed. The ranked
causes determine the next implementation target. Template registration remains blocked
until non-PHI operator-approved canonical references are supplied.
