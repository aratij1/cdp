# CDP UB-04 optimization report

Status date: 2026-08-22. Phase 5 implementation is complete; accuracy impact remains unmeasured on a governed UB-04 holdout.

## Dedicated service-line path

The UB-04 engine reconstructs the 22 FL42–FL48 rows separately from CMS-1500. Registered OCR tokens are assigned by token-center geometry to versioned row and column boundaries, ordered within cells, normalized by column type, and assembled into typed service lines containing revenue code, description, HCPCS/HIPPS, service date, units, charge and non-covered charge.

Validation covers:

- Four-digit revenue-code syntax and presence
- CPT/HCPCS syntax plus optional versioned reference membership
- Service-date parsing and future-date rejection
- Strictly positive units
- Non-negative covered and non-covered charges
- Required charge presence
- Per-row confidence
- Reconciliation of service-line charges to the claim total using configured tolerance

The reconstruction policy is versioned as `ub04-service-lines-v2`; HCPCS reference version is retained in every result when supplied. Registration, unassigned-token ratio, row confidence, and total tolerance thresholds are externalized in `config/table_templates/ub04_service_lines.yaml`.

## Failure routing

Docling is not part of the standard fixed-field path. It becomes eligible only after regional OCR has been attempted and geometric reconstruction fails. Low registration, empty regional OCR, excessive unassigned tokens, or zero reconstructed rows produce a fail-closed `DOCLING` escalation. When geometry succeeds but healthcare validation or financial reconciliation fails, the result routes to HITL because another layout model cannot authoritatively repair an invalid code or contradictory total.

Docling remains additive evidence and cannot directly auto-accept critical fields.

## Baseline and limitations

The last governed development baseline is 75.93% UB-04 field accuracy, 72.13% overall accuracy, 65.56% critical accuracy, zero measured false accepts, 0% STP and 76.67% claim review. No new metric delta is claimed from unit tests. The official UB-04 canonical registration image and an untouched representative UB-04 holdout are still required before promotion.

Decision: `NEEDS_MORE_DATA`.
