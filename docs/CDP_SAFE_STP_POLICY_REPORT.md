# Phase 10 — Safe Straight-Through Processing Policy

## Outcome

The platform now has one explicit, configurable, fail-closed claim-level STP decision. It emits exactly one of:

- `STP_SAFE`: every configured gate passes and all C3 fields are independently verified.
- `STP_STANDARD`: every configured gate passes, without the C3-independent-verification qualification for safe status.
- `REVIEW_REQUIRED`: the document is processable, but one or more evidence or validation gates remain unresolved.
- `REJECTED`: document/process integrity, wrong-page, or wrong-crop checks fail.

## Mandatory gates

STP requires complete required fields, resolved critical fields, field-specific evidence-policy satisfaction, critical confidence floors, deterministic validation, no unresolved contradictions, acceptable registration and page-classification confidence, valid service lines, and all mandatory claim validations.

Claim quality is the minimum of required-field completeness, minimum critical-field confidence, registration confidence, page-classification confidence, and critical reference/independent-evidence quality. It is not an average and therefore cannot hide one weak critical component behind stronger unrelated fields.

An empty required-field or critical-field policy fails closed. The number of open review tasks is reported as context but is not treated as proof that a claim is safe or unsafe; the evidence gates determine the result.

## Verification

The focused STP, evidence, crop, UB-04, and legacy finalization suite passes 27 tests. The tests cover C3 safe qualification, standard STP, evidence-policy failure despite confidence 1.0, weakest-link claim quality, contradictions, incomplete required fields, wrong-page/crop rejection, empty-policy failure, and review-task proxy avoidance.

## Release decision

No existing claim is newly asserted as STP in this phase. The last measured safe STP rate remains 0%, because the current benchmark lacks a new untouched holdout and several production evidence inputs are unavailable. The policy is implemented, but promotion remains `NEEDS_MORE_DATA` until Phase 11 independent evaluation.
