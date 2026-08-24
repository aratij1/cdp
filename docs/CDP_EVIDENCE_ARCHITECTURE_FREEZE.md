# CDP Evidence Architecture Freeze

This document freezes semantics, not thresholds.

## Evidence classes and authority

- OCR candidates are observations, never independent confirmation merely because engine names differ.
- Structural localization, deterministic validation, cross-field reconciliation, authorized reference data, and human confirmation remain distinct evidence classes.
- `EvidenceDependencyService` is the dependency authority. Shared pixels, crop, observation, localization, preprocessing, model family, parent candidate, or upstream dependency may make candidates correlated.
- Missing lineage produces `UNKNOWN`, and unknown dependency cannot earn independence credit.
- `ReferenceEvidenceService` is the single bridge from configured reference providers. Disabled and test-fixture sources cannot silently become production authority.
- `EvidenceDecisionService` is the sole machine field-disposition authority.
- `ClaimDecisionService` is the sole claim blocker and STP authority.

## Frozen invariants

1. Same-page or same-crop OCR agreement is not independent evidence by default.
2. Unknown provenance fails closed.
3. Deterministic format validity does not prove semantic correctness.
4. Cross-field evidence must name its relationship and version.
5. Reference evidence must carry provider, dataset version, source record, snapshot time, and checksum.
6. Extraction, retry, and escalation components may collect candidates but may not bypass field decision policy.
7. Claim STP requires accepted blocking fields under `claim-decision-v1`; it may not infer acceptance from raw extraction confidence.
8. Cloud/VLM paths remain disabled on the common path and may return candidates only.

## Frozen versions for Phase 8.10

- Runtime evidence: `evidence-policy-v4-dependency-aware`
- Historical Phase 8.10 evaluation evidence: `evidence-policy-v4-dependency-aware-balanced`
- Claim evidence: `claim-evidence-v1`
- Claim decision: `claim-decision-v1`
- Reference adapter: `reference-evidence-v1`
- Evidence dependency service: rule-based provenance classification in commit `3a7d5d1`

The runtime/evaluation policy difference is preserved as historical fact and must not be normalized away in reports.
