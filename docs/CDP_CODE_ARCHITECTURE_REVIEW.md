# CDP code architecture review

Review date: 2026-08-22. Reviewed commit baseline: `f8f5f39b` on `main`.

## Executive finding

The repository had a P0 dual-decision architecture. Offline paths used candidate consensus and `EvidenceReconciler`, while the live validation worker assigned `VALIDATED_AUTOMATICALLY` whenever hard validation returned no errors. The live SQL persistence mapper also discarded `ExtractedField.candidates`, making independent evidence unavailable after extraction. This allowed a critical field to bypass the configured evidence policy.

The first remediation unit introduces `packages/evidence_decision` as the final-disposition authority, persists OCR candidate evidence, and makes live validation delegate to that service. Evaluation's HITL optimizer now invokes the same service before changing `accepted`.

## Live event trace

| Stage | Entrypoint and input | Output / persistence | Implementation and behavior | Deployment / tests |
|---|---|---|---|---|
| Upload | `apps/ingestion_api/service.py`; HTTP upload | `document.received`; documents/outbox/object store | SHA-based idempotency and transactional outbox; rejects invalid intake | ingestion Helm chart; ingestion/service tests |
| Preparation | `workers/document_preparation/consumer.py`; `document.received` | pages plus `page.classification.requested` | decode, normalize, quality/transforms; transaction retry is consumer-level | preparation Helm/KEDA; preparation tests |
| Classification | `workers/page_detection/consumer.py`; classification request | standard or unstructured extraction request | anchors/layout/template routing; persists classification/registration evidence | page KEDA; classification/alignment tests |
| CMS-1500 extraction | `workers/standard_form_extraction/consumer.py`; `extraction.standard.requested` | extracted fields and `extraction.completed` | RapidOCR is the live default; regional crops; adaptive reference alignment and crop firewall when a canonical reference is available | standard-form KEDA; extraction worker tests |
| UB-04 extraction | same standard worker | header fields and service-line cells | standard regional extraction is live; specialized `UB04ServiceLineExtractor` exists but is not the live consumer path | table/unit tests; runtime convergence remains P1 |
| Bundle D | page detector emits `extraction.unstructured.requested` | no live consumer found | adapters and offline orchestration exist, but there is no event consumer entrypoint | KEDA manifest exists without executable worker: P1 defect |
| Validation / reconciliation | `workers/validation/consumer.py`; `extraction.completed` | field retry requests plus `claim.validated` | now calls `EvidenceDecisionService`; hard validation is evidence, not authority; candidates survive SQL mapping | validation KEDA; validation and decision-service tests |
| Retry | `workers/retry/consumer.py`; `field.retry.requested` | retry, validation, or human-review event | router selects an evidence source; result is appended, then canonical decision service controls value/disposition and next event | retry KEDA; retry/router/convergence tests |
| HITL | `apps/human_review_api/consumer.py`; `human.review.requested` | idempotent field task | deterministic UUID and get-before-add; evidence-rich schema supported | HITL Helm/KEDA; API/consumer tests |
| Output | `workers/output_generation/consumer.py`; output request | immutable artifacts and `output.completed` | consumes canonical critical-field dispositions; deterministic claim validation is retained for the reconciliation report, not field acceptance | output KEDA; golden/output/convergence tests |

## Runtime/evaluation divergences

| Severity | Divergence | Evidence | Remediation state |
|---|---|---|---|
| P0 | Hard validation directly auto-accepted live fields | former branch in `workers/validation/consumer.py` | fixed in first unit |
| P0 | Candidate evidence disappeared at SQL boundary | mapper omitted `ExtractedField.candidates` | fixed; migration `005_ocr_candidate_evidence.sql` |
| P0 | Evaluation HITL logic made dispositions outside reconciliation | `evaluation/optimize_hitl_evidence.py` | final gate now delegates to common service |
| P0 | Retry adapters updated canonical ORM values and immediately requeued | `workers/retry/consumer.py` | fixed: append evidence then decide |
| P0 | Output used legacy disposition strings | `workers/output_generation/consumer.py` | fixed: canonical terminal set |
| P1 | UB-04 specialized row engine is not the live standard consumer | `workers/table_extraction/ub04_service_lines.py` vs standard extractor | open |
| P1 | Bundle D has no live Kafka consumer | no `workers/unstructured_extraction/consumer.py` | open |
| P1 | Runtime persists through `apps.ingestion_api.db` | imports across workers | open persistence-boundary remediation |

## Safety conclusions

- RapidOCR is already the configured live standard-form primary; no new model is justified.
- A missing canonical reference causes rescale-only extraction and review markings. CMS assets exist; UB-04 canonical activation remains incomplete.
- Retry has bounded routing concepts but its canonical-value mutation and requeue behavior require convergence and poison-message tests.
- Kafka topics include a DLQ, but consistent DLQ publication/replay audit is not implemented across consumers.
- The current development metrics remain 72.13% overall, 65.56% critical, 76.67% claim HITL, 0% safe STP, and zero measured baseline false accepts. They are not production claims.
