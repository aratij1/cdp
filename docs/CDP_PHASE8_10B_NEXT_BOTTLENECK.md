# Phase 8.10B next bottleneck

| Form | Field | Correct reviewed | Claims blocked | Single blockers | Missing evidence | Lowest-cost legitimate evidence |
|---|---|---:|---:|---:|---|---|
| CMS1500 | provider_npi | 30 | 30 | 0 | MISSING_E2 | independent local representation |
| UB04 | federal_tax_no | 30 | 30 | 0 | MISSING_E6 | cross-field claim reconciliation |
| UB04 | provider_npi | 30 | 30 | 0 | MISSING_E2 | independent local representation |
| CMS1500 | cpt_hcpcs | 28 | 28 | 0 | MISSING_E2 | independent local representation |
| CMS1500 | total_charge | 27 | 27 | 0 | MISSING_E6 | cross-field claim reconciliation |
| CMS1500 | patient_name | 26 | 26 | 0 | MISSING_E6 | cross-field claim reconciliation |
| UB04 | member_id | 26 | 26 | 0 | MISSING_E2 | independent local representation |
| CMS1500 | insured_name | 25 | 25 | 0 | MISSING_E6 | cross-field claim reconciliation |
| CMS1500 | member_id | 24 | 24 | 0 | MISSING_E6 | cross-field claim reconciliation |
| CMS1500 | relationship | 24 | 24 | 0 | MISSING_E6 | cross-field claim reconciliation |
| UB04 | patient_name | 24 | 24 | 0 | MISSING_E6 | cross-field claim reconciliation |
| UB04 | provider_name | 24 | 24 | 0 | MISSING_E6 | cross-field claim reconciliation |
| UB04 | total_charge | 24 | 24 | 0 | MISSING_E2 | independent local representation |
| UB04 | type_of_bill | 24 | 24 | 0 | MISSING_E6 | cross-field claim reconciliation |
| CMS1500 | provider_name | 23 | 23 | 0 | MISSING_E6 | cross-field claim reconciliation |
| UB04 | principal_diagnosis | 23 | 23 | 0 | MISSING_E6 | cross-field claim reconciliation |

No claim has exactly one unresolved blocking field, so no individual evidence addition can unlock a complete claim on this pack. The largest low-cost, generalizable gap is E6 (274 correct-but-reviewed fields).

## Exactly one next bottleneck

Correct total-charge candidates lack qualified claim-total/line-total reconciliation evidence.

## Exactly one next experiment

On the frozen candidates, evaluate the existing deterministic `CLAIM_TOTAL_CONFIRMED` / `LINE_TOTALS_RECONCILED` path for `total_charge` only and measure false accepts and reduction in correct-but-reviewed fields. Do not change policy, OCR, localization, UB row reconstruction, or any other field.

Status: **COMPLETED — PROMOTE**. The experiment reduced total-charge correct-but-reviewed fields by 24 with 24/24 accepted values correct, zero total-charge false accepts, and zero non-total-charge decision changes. See `CDP_PHASE8_10B_TOTAL_CHARGE_E6_EXPERIMENT.md`.
