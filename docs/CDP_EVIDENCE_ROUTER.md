# CDP evidence router

The evidence router chooses the cheapest eligible next action by field family, prior attempts, reference availability, tenant cloud policy, remaining budget and remaining SLA. Routes and action cost/latency estimates are configuration-driven in `config/adaptive_routing.yaml`.

## Gate order

1. Registration below 0.60 routes directly to HITL; it cannot be accepted or OCR-confidently overridden.
2. A failed crop-safety check receives one bounded expanded-crop attempt, then HITL.
3. Registration from 0.60 to below 0.80 receives one bounded crop expansion.
4. Acceptance requires evidence-policy satisfaction, at least one completed deterministic validation, no contradiction, calibrated confidence at threshold, and normal registration quality.
5. A low-quality crop receives one alternate-preprocessing retry after RapidOCR.
6. Remaining actions follow the field-specific local-first route and must fit budget/SLA and cloud policy.

Current routes use Tesseract for identifiers, NPI, dates, codes and amounts; PaddleOCR for names and addresses; Docling only for failed table paths; and cloud services only when policy explicitly permits them. NPI never routes to Gemini in the normal policy.

## Safe STP

Claim-level STP uses the weakest mandatory gate, not average field confidence. It requires all required fields resolved, all critical evidence and validation policies satisfied, registration and page classification above configured thresholds, passed wrong-page/wrong-crop checks, no unresolved contradiction, valid service lines and successful mandatory claim validations. `STP_SAFE` additionally requires every C3 field to have independent OCR/deterministic verification or verified authoritative reference evidence.

Outcomes are `STP_SAFE`, `STP_STANDARD`, `REVIEW_REQUIRED`, or `REJECTED`, with machine-readable reasons and policy version.
