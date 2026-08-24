# CDP Runtime / Evaluation Parity

Runtime and evaluation continue to use `EvidenceDecisionService` as the sole field
authority and `ClaimDecisionService` as the sole claim authority. OCR candidate
serialization round trips preserve original confidence and provenance, and the same
serialized `DecisionContext` produces the same complete `FieldDecision`.

Phase 8.8C removes the evaluation-only shortcut that treated engine diversity as
independence. Evaluation adapters load recorded `EvidenceProvenance` when present;
when absent they pass unknown provenance into the canonical decision service.

Parity tests cover direct versus persisted candidates, context serialization, route
lifecycle status, reference authorization, and fail-closed missing lineage. No truth,
source identity, or dataset role is available to the decision service.

Status remains `PASS` for canonical field and claim contracts; production
infrastructure replay is `NOT_RUN`. Evaluation-only confirmation candidates are still
removed from runtime construction with an explicit rejected route ID, and shadow
execution has no authority to mutate STP, HITL, or output. Claim decisions remain
byte-equivalent for identical serialized field decisions and claim policy.

Evidence: `tests/integration/test_runtime_evaluation_decision_parity.py`,
`tests/integration/test_claim_runtime_evaluation_decision_parity.py`,
`tests/unit/cases/test_route_registry.py`, and
`tests/unit/cases/test_phase8_8c_evidence_semantics.py`.
