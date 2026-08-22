# CDP Phase 3 Claim-Level STP Report

## Outcome

The canonical synthetic evaluation frontier reaches **80.00% claim STP** and **20.00% claim HITL**, with **zero observed false accepts**. Raw extraction remains frozen at 99.00% (594/600).

| Metric | Phase 2 frontier | Phase 3 frontier | Change |
|---|---:|---:|---:|
| Safe field coverage | 75.83% (455/600) | 85.83% (515/600) | +10.00 pp |
| Field HITL/unresolved | 24.17% (145/600) | 14.17% (85/600) | -10.00 pp |
| Claim STP | 34.17% (41/120) | 80.00% (96/120) | +45.83 pp / 55 claims |
| Claim HITL | 65.83% (79/120) | 20.00% (24/120) | -45.83 pp |
| False accepts | 0 | 0 | unchanged |

This is a corrected synthetic evaluation result, not a production promotion. The member-ID route remains the only `PRODUCTION_APPROVED` confirmation route. Every non-member route is `EVALUATION_ONLY`, and runtime construction rejects those routes.

## Canonical claim authority

`ClaimDecisionService` is now the only authority for:

- `STP_SAFE`
- `STP_STANDARD`
- `FIELD_REVIEW_REQUIRED`
- `CLAIM_REVIEW_REQUIRED`
- `DOCUMENT_REJECTED`

It consumes field decisions, claim evidence, contradictions, integrity state, and explicit policy versions. It returns blocking and non-blocking unresolved fields, critical blockers, reason codes, and `stp_eligible`. It never treats the absence of a review task as evidence of STP.

Validation serializes the complete canonical context and decision on `claim.validated`. Output consumes that decision and, when the serialized field context is present, recomputes it through the same service and rejects any parity mismatch. The old output-specific critical-field finalization branch is removed. The legacy `SafeSTPPolicy` is now only a compatibility adapter that delegates disposition authority to `ClaimDecisionService`.

Evaluation and dashboard publication consume canonical claim decisions. When no canonical decision is present, claim STP/HITL is reported as unavailable rather than inferred from correctness or review-task counts.

## Safe evidence changes

Two truth-blind defects produced the measured improvement:

1. ICD-10 E4 syntax now recognizes both display and compact electronic-claim representations. For example, `Z00.00` and `Z0000` are syntactically equivalent. This does not assert that a code exists in an authorized code set; existence remains E5 reference evidence.
2. E2 agreement is now field-aware normalized exact agreement. Name punctuation/scan artifacts can normalize away, dates and identifiers use representation-safe canonicalization, while money retains numeric decimal semantics so `10.00` cannot falsely agree with `1000`.

These changes safely accepted 45 diagnosis fields and 15 patient-name fields that already had independent agreement and the remaining required evidence. All 60 additional acceptances were correct on this benchmark; no threshold was reduced.

## E2 measurement and route state

Agreement precision is measured against the corrected synthetic labels and takes precedence over standalone secondary-engine accuracy.

| Field | Evaluated | Agreements | Agreement coverage | False agreements | Agreement precision | Mean confirmation latency |
|---|---:|---:|---:|---:|---:|---:|
| `insured_id_number` | 60 | 59 | 98.33% | 0 | 100.00% | 1886.6 ms |
| `patient_name` | 120 | 99 | 82.50% | 0 | 100.00% | 931.2 ms |
| `patient_dob` | 120 | 105 | 87.50% | 0 | 100.00% | 215.6 ms |
| `total_charge` | 60 | 59 | 98.33% | 0 | 100.00% | 272.0 ms |
| `provider_npi` | 60 | 60 | 100.00% | 0 | 100.00% | 236.2 ms |
| `type_of_bill` | 60 | 45 | 75.00% | 0 | 100.00% | 446.3 ms |
| `principal_diagnosis` | 60 | 45 | 75.00% | 0 | 100.00% | 490.2 ms |
| `federal_tax_no` | 60 | 43 | 71.67% | 0 | 100.00% | 526.7 ms |

The candidate frontier uses 600 recorded local confirmation calls, adds no cloud cost, and estimates 967.77 ms mean / 2571.95 ms P95 latency including confirmation. Non-member routes require an independent holdout with zero observed false agreements, sufficient sample size, and capacity approval before production promotion.

## Claim E6

`ClaimEvidenceBuilder` now emits deterministic E6 evidence and explicit contradictions for:

- claim-total versus service-line-total reconciliation with versioned absolute and relative tolerances;
- units multiplied by rate versus line charge;
- statement, service, admission, and discharge date ordering;
- repeated member identity and self-relationship consistency;
- repeated provider identity consistency as E6, never E5;
- UB-04 revenue/HCPCS/unit/charge service-line coherence.

The synthetic frontier does not contain the service-line and relationship inputs needed for a measured E6 gain, so no E6 improvement is claimed. The implementation is wired into live validation and covered by deterministic tests.

## Remaining blocker Pareto

Twenty-four claims remain non-STP. Eight are single-blocker claims. `patient_name` has the highest exact unlock value: five claims (4.17 percentage points of total STP) could unlock if that evidence is resolved safely. The detailed per-field and blocker-set analysis is in `docs/CDP_CLAIM_STP_BLOCKER_PARETO.md`.

No blocking field was relabeled merely to improve STP. Required, critical, blocking, and review-on-unresolved remain explicit, separate policy dimensions in `docs/CDP_FIELD_BLOCKING_MATRIX.md`.
