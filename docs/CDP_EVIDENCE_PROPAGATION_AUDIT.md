# CDP Evidence Propagation Audit

This audit covers the canonical field path:

`OCR provider → OCRCandidate → candidate persistence → validation → FieldEvidenceBundle → reconciliation → EvidenceDecisionService → disposition`

## Canonical evidence taxonomy

| Class | Repository-wide meaning | Independence rule |
|---|---|---|
| E1 | Single extraction evidence | One OCR/extraction family; confidence is not correctness probability. |
| E2 | Independent extraction agreement | Exact normalized agreement from at least two engine families. Same-engine preprocessing variants never count. |
| E3 | Structural/geometric evidence | Measured registration/ROI evidence, or explicitly identified `SYNTHETIC_CANONICAL` structure. |
| E4 | Deterministic healthcare/business evidence | Truth-blind validators with `PASS`, `FAIL`, `NOT_APPLICABLE`, or `INSUFFICIENT_DATA`. |
| E5 | Authoritative reference evidence | Counts only when the source state is `AUTHORIZED`; `TEST_FIXTURE` and `DISABLED` do not count. |
| E6 | Cross-field or claim-consistency evidence | Claim relationships, never relabeled as authoritative truth. |
| E7 | Independent cloud/AI evidence | A separately governed provider family. |
| E8 | Human-verified evidence | Recorded reviewer disposition and provenance. |

## Findings and remediation

| Boundary | Finding | Classification | Remediation/status |
|---|---|---|---|
| Candidate persistence → retry | Retry candidates were appended, but evidence context was not preserved across retry events. | `EVIDENCE_NOT_PROPAGATED` | Validation now persists structural, deterministic, cross-field, reference-state, and form-policy context. Retry restores it before the canonical decision call. |
| Registration → decision | Older evaluation code defaulted missing registration to `1.0`. | `EVIDENCE_NOT_PROPAGATED` / fabricated E3 | Decision context now defaults to `None`; real runtime pages require accepted measured alignment. Synthetic replay explicitly emits `STRUCTURAL_SOURCE=SYNTHETIC_CANONICAL`. |
| Deterministic validation → retry | Retry reused only a boolean hard-pass flag and could apply it to a disagreeing candidate. | Candidate/evidence lineage defect | Retry recomputes deterministic evidence and only reuses it when the retry agrees with the canonical value; conflicts remain unresolved. |
| Reference → bundle | A verified fixture could previously look equivalent to an authorized provider. | E5 authorization defect | `DISABLED`, `TEST_FIXTURE`, and `AUTHORIZED` are explicit. Only `AUTHORIZED` creates E5. |
| Evidence policy → reconciliation | Two independent policy systems could disagree about finalization. | Policy propagation defect | `EvidenceDecisionService` now owns the E1–E8 acceptance policy; the reconciler selects candidates, checks calibration/contradictions, and no longer re-finalizes with its legacy policy in this path. |
| Evidence bundle → audit | Bundles lacked policy, missing-class, contradiction, and stable candidate lineage. | Auditability defect | `FieldEvidenceBundle` now records stable candidate IDs, deterministic evidence IDs, contradictions, available/missing classes, and policy ID/version. |
| Measured confirmation artifacts → runtime | 515 correct primary values have a measured agreeing candidate outside runtime persistence. | `EVIDENCE_NOT_PROPAGATED` | Member ID uses its benchmark-selected Rapid route. New non-member Paddle confirmations remain evaluation-only pending an independent production holdout. |

## Runtime/evaluation parity

Both paths construct `DecisionContext` and call `EvidenceDecisionService.decide`. The parity test serializes the context through its JSON contract and asserts identical candidate IDs, evidence items, selected value, reason codes, and disposition. Evidence IDs are derived deterministically so equivalent contexts are byte-stable apart from surrounding event metadata.

The synthetic replay is production-equivalent at the decision boundary, but its E3 source is a canonical synthetic contract. It is not production accuracy or a production STP qualification.
