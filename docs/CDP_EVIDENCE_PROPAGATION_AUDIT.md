# CDP Evidence Propagation Audit

Canonical provenance now propagates through:

`OCRCandidate -> FieldEvidence -> JSON database column -> runtime adapter -> DecisionContext -> evidence bundle -> audit`

`EvidenceProvenance` includes page and representation IDs, observation ID, crop hash
and URI, localization ID/method/version, registration transform, preprocessing
profile/version, engine/model lineage, parent/source candidate IDs, bbox, and timestamp.
All fields are optional so pre-8.8C records remain loadable. Missing fields are not
fabricated: dependency classification becomes `UNKNOWN`.

The standard-form extraction path populates provenance for full-page-observation and
regional candidates, preserves each candidate's own confidence, and hashes the actual
crop pixels when the image is available. The database already persists `FieldEvidence`
as JSON, so the nested model requires no destructive schema migration. Runtime
reconstruction prefers original engine, preprocessing, model, bbox, and lineage over
generic placeholders.

The unchanged 8.8A replay demonstrates the compatibility boundary: all 243 agreement
groups are unknown because those historical serialized candidates contain no canonical
provenance. This is reported explicitly and is the reason Phase 8.8C is not complete
for promotion despite its code path being implemented.

## Canonical evidence taxonomy

| Class | Repository-wide meaning | Qualification rule |
|---|---|---|
| E1 | Single extraction evidence | Supporting evidence only; confidence is not correctness. |
| E2 | OCR agreement | Only `OCR_AGREEMENT_INDEPENDENT` is policy-eligible. |
| E3 | Structural/geometric evidence | C2/C3 requires the measured field ROI, not a page mean. |
| E4 | Deterministic evidence | C2/C3 requires a strong subtype; format plausibility is weak. |
| E5 | Authoritative reference | Requires an `AUTHORIZED` source. |
| E6 | Cross-field/claim consistency | Never relabeled as reference truth. |
| E7 | Governed AI evidence | Separately governed; cloud remains disabled here. |
| E8 | Human verification | Reviewer disposition plus provenance. |

## Earlier propagation remediations retained

Phase 8.8C preserves the existing retry evidence context, non-fabricated registration
defaults, retry-time deterministic recomputation, explicit reference authorization
states, deterministic evidence IDs, route lifecycle governance, and the separation of
candidate reconciliation from final policy authority. Measured confirmations outside
runtime persistence remain evaluation-only until independently qualified.
