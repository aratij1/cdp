# CDP Runtime/Evaluation Parity

Status: `PASS` for canonical field and claim decision contracts; production infrastructure replay remains `NOT_RUN`.

Both adapters construct the same `DecisionContext` and call the sole `EvidenceDecisionService`. Retry appends evidence, validation decides through that service, and output consumes canonical dispositions. Claim decisions are produced only by `ClaimDecisionService`.

Contract coverage proves:

- identical persisted candidates, evidence, policy, and `PRODUCTION_APPROVED` route status produce an identical `FieldDecision` in runtime and evaluation modes;
- route execution mode is recorded in the bundle but is not a decision input when the route status grants both modes authority;
- identical serialized `FieldDecision[]` and claim policy produce byte-equivalent `ClaimDecision` payloads;
- `EVALUATION_ONLY` confirmation candidates are removed before runtime evidence construction and leave a `ROUTE_STATUS_REJECTED` reason and rejected route ID;
- shadow execution returns the original canonical candidate and has no API capable of mutating STP, HITL, or output.

The frozen 80% result was separately audited across all 96 synthetic STP claims. All governed evaluation assertions pass, but every STP claim uses at least one evaluation-only route, so production-eligible STP claims remain zero. This separates evaluation qualification from production authority.

Evidence: `tests/integration/test_runtime_evaluation_decision_parity.py`, `tests/integration/test_claim_runtime_evaluation_decision_parity.py`, `tests/unit/cases/test_route_registry.py`, and `evaluation_results/production_readiness/policy_correctness_audit.json`.
