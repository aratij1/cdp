# CDP accuracy/cost Pareto

Status date: 2026-08-22. Only the governed development baseline and configured cost model are measured/available. Layer deltas below are experiment slots, not inferred accuracy claims.

| Layer | Accuracy gain | Critical gain | Review reduction | STP gain | False accepts | Added latency | Added cost/page | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| RapidOCR only | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Local CPU | Experiment required |
| + deterministic validation | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Negligible CPU | Experiment required |
| + selective Tesseract/Paddle | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Route dependent | Experiment required |
| + reference matching | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Config estimate $0.00005/call | Experiment required |
| + adaptive registration | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | Not isolated | CPU dependent | Experiment required |
| + Docling | Not measured | Not measured | Not measured | Not measured | Not measured | Config 1.5 s/call | Config $0.001/call | Disabled/common-path excluded |
| + Textract | Not measured | Not measured | Not measured | Not measured | Not measured | Config 2.0 s/call | Config $0.003/call | Selective only |
| + Gemini Cheap | Not measured | Not measured | Not measured | Not measured | Not measured | Config 1.5 s/call | Config $0.002/call | Selective only |
| + Gemini Standard | Not measured | Not measured | Not measured | Not measured | Not measured | Config 3.0 s/call | Config $0.010/call | Selective only |
| + Gemini Advanced | Not measured | Not measured | Not measured | Not measured | Not measured | Config 7.0 s/call | Config $0.030/call | Selective only |

The development baseline is 72.13% overall accuracy, 65.56% critical accuracy, zero measured false accepts, 0% STP, 76.67% review and 20% perfect claims. At the configured $1.00 reviewed-page labor assumption, total cost is $0.76936/page: $0.00210 routing, $0.00010 compute, $0.00050 storage/orchestration and $0.76667 HITL.

Planning scenarios are $0.30270/page at 30% review, $0.10270 at 10%, and $0.05270 at 5%. They are not achieved outcomes. HITL dominates current cost, but review must only be removed through independently verified evidence.

## Phase 6 controls

Cloud models are selected through versioned aliases in `config/ai_models.yaml`; business orchestration does not embed provider model names. Every request is crop-only, tenant/PHI/region/model authorized, rate limited, budget reserved, bounded by timeout/retry/circuit breaker, and audited without field content. Gemini responses must exactly satisfy the structured contract. Textract and Gemini results are auxiliary candidates with `acceptance_authority=false` and must return to reconciliation.

Promotion requires an experiment-ledger record for each incremental layer, including accuracy, critical accuracy, review/STP, false accepts, P95 latency and total cost. A costly layer with negligible safe review reduction is rejected.
