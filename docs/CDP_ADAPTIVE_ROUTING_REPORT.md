# Phase 7 — Adaptive Escalation Routing

## Outcome

Phase 7 adds a configurable field-level decision engine. It selects the next eligible evidence source using field family, prior attempts, registration quality, reference availability, cloud policy, remaining SLA, and remaining budget.

Acceptance is fail-closed: confidence alone is insufficient. The field evidence policy must be satisfied, deterministic validations must pass, and unresolved contradictions must be absent.

## Routes

- Member identifiers: RapidOCR → constrained Tesseract → authoritative reference → Gemini Cheap → HITL.
- NPI: RapidOCR → constrained Tesseract → authoritative reference → HITL. Gemini is structurally excluded.
- Names: RapidOCR → PaddleOCR → authoritative reference → Gemini Cheap → HITL.
- Numeric, date, and code fields: RapidOCR → constrained Tesseract → authoritative reference → Textract → HITL.
- Tables: RapidOCR geometry → Docling → authoritative reference/cross-field evidence → Gemini Cheap → HITL.

Registration confidence from 0.60 through 0.79 triggers at most one bounded crop expansion before the normal route resumes. Cloud actions are skipped unless explicitly allowed. Ineligible actions are skipped when their configured cost or latency exceeds the remaining budget or SLA.

## Verification

- Focused policy and legacy-router tests: 18 passed.
- Full suite: 589 passed, 5 skipped, 1 existing frozen-manifest failure.
- The remaining failure is the pre-existing hash mismatch for `config/validation/cms1500_thresholds.yaml` in the frozen `extraction-v2` manifest; Phase 7 does not modify either file.

## Accuracy and release decision

No new untouched labeled holdout was authorized for this phase, so no accuracy uplift is claimed. The last measured overall field accuracy remains 72.13%, with zero measured total-field or critical-field false accepts. Safe STP remains 0%.

Decision: `NEEDS_MORE_DATA`. The adaptive policy is ready for shadow telemetry; production acceptance and STP remain gated on an untouched holdout and the later production-gate phase.
