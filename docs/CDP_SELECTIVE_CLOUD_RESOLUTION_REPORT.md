# Phase 8 — Selective Gemini and Textract Resolution

## Outcome

Phase 8 connects adaptive routing decisions to the existing governed AI gateway. Only decisions for `TEXTRACT`, `GEMINI_CHEAP`, `GEMINI_STANDARD`, or `GEMINI_ADVANCED` can invoke a cloud provider. Local, reference, acceptance, and HITL decisions make no cloud call.

## Safety controls

- Only field or table crop contracts are accepted; whole-document input is not representable.
- Crop content is integrity-bound by SHA-256 before execution.
- Tenant enablement, PHI approval, region and model allowlists, budgets, rate limits, timeouts, retries, circuit breakers, and PHI-safe audit records are enforced by the central gateway.
- NPI fields cannot use Gemini, even if a caller attempts to bypass the adaptive route.
- Cloud calls are capped per document-field pair.
- Gemini uses temperature zero and a strict JSON response schema.
- Returned values are auxiliary candidates with `acceptance_authority=false` and `requires_reconciliation=true`.
- Empty, abstained, or pattern-invalid responses remain insufficient evidence.

## Verification

The focused Phase 7/8 and provider suite passes 19 tests. No live cloud credentials or external PHI processing were used; providers are transport-injected and tests use deterministic fakes.

## Accuracy and release decision

This phase changes evidence acquisition, not the measured benchmark population. No untouched labeled holdout was supplied, so the last measured overall accuracy remains 72.13%, false accepts remain zero, and safe STP remains 0%.

Decision: `NEEDS_MORE_DATA`. The implementation is suitable for controlled shadow evaluation after tenant cloud authorization and provider transport configuration. Cloud evidence cannot independently enable production STP.
