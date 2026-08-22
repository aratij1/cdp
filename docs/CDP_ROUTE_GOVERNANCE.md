# CDP Route Governance

Every configured field/form/engine-pair route now has one explicit lifecycle: `DISABLED`, `EXPERIMENTAL`, `EVALUATION_ONLY`, `SHADOW`, `PRODUCTION_APPROVED`, or `DEPRECATED`.

The registry records route ID, field, form, engines, preprocessing profile, policy version, benchmark and sample count, accuracy, agreement precision, false agreements, latency, cost status, lifecycle, and approval provenance. A production-approved route cannot load without approver and timestamp. Missing or malformed registries fail closed.

Runtime authority includes only `PRODUCTION_APPROVED`. Evaluation must explicitly select evaluation mode. Shadow execution includes only `SHADOW` routes and cannot alter canonical output. Evidence bundles record route ID, lifecycle, execution mode, and rejected route IDs.

Current status remains unchanged:

- `CMS1500.insured_id_number.paddleocr.rapidocr.v1`: `PRODUCTION_APPROVED` under its pre-existing, narrowly scoped member-ID approval.
- All seven non-member routes: `EVALUATION_ONLY`.
- No route is `SHADOW`; no route was promoted from synthetic evidence.

The route promotion gate is field-, form-, and engine-pair-specific. Evaluation-to-shadow requires an independent frozen holdout, per-route sample size, accuracy, agreement precision, zero critical false agreements, measured latency, and measured cost. Shadow-to-production additionally requires runtime shadow sample size and operational reliability.
