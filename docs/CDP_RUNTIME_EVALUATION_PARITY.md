# CDP runtime/evaluation parity

Status: validation, retry, evaluation, and output final-disposition convergence implemented.

Both live validation and the governed HITL candidate optimizer now construct `DecisionContext` and invoke `packages.evidence_decision.EvidenceDecisionService`. The service owns calibrated reconciliation, field evidence policy, criticality handling, registration/wrong-crop gating, reference contradiction behavior, blocking policy, reason codes, next action, and policy version.

The persistence boundary now retains every `FieldEvidence` item as JSON. Live validation converts those persisted items to the authoritative `OCRCandidate` contract. Evaluation converts recorded provider candidates to the same contract and cannot set `accepted` unless the shared service returns `AUTO_ACCEPTED` or `REFERENCE_CONFIRMED`.

Tests prove that critical hard-validation success is insufficient, high OCR confidence cannot override wrong-crop evidence, reference contradiction blocks acceptance, a C0 optional field can be unresolved without blocking, and reference-confirmed independent OCR is accepted through the same policy.

Retry providers now append immutable `FieldEvidence` records and cannot overwrite the canonical value before `EvidenceDecisionService` returns `AUTO_ACCEPTED` or `REFERENCE_CONFIRMED`. Failed/insufficient attempts are routed onward with the canonical reason codes and policy version; HITL receives the complete candidate trail. Output recognizes only `AUTO_ACCEPTED`, `REFERENCE_CONFIRMED`, or `HUMAN_CONFIRMED` for critical fields and explicitly rejects the former `VALIDATED_AUTOMATICALLY` shortcut.

The runtime/evaluation integration fixture feeds equivalent RapidOCR, PaddleOCR, deterministic-validation, and reference evidence through both adapters and asserts identical disposition, reason codes, and policy version. The full unit suite passes 647 tests and the focused convergence/parity suite passes 13 tests.

Remaining parity work is orchestration coverage rather than a known duplicate final-decision branch: add a Kafka/database/object-store integration test spanning extraction through output, and migrate specialized UB-04 and Bundle D paths onto the same live orchestration.
