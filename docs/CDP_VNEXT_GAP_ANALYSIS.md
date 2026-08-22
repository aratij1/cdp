# CDP vNext Gap Analysis

Assessment baseline: commit `c52b164`. Status reflects repository evidence, not product claims.

| Current capability | Target capability | Gap | Severity | Implementation location | Action | Dependencies | Tests required |
|---|---|---|---|---|---|---|---|
| Kafka-compatible event bus, envelopes, outbox | Horizontally scalable event workers | KEDA/lag SLO validation is incomplete | High | `packages/events`, `deploy/` | Refactor | Redpanda, Helm, KEDA | replay, duplicate, poison-event, scale tests |
| Template/anchor/grid routing | Cheap alignment then SIFT/FLANN/RANSAC | Phase 1 adaptive registration implemented; persistence wiring remains | High | `workers/page_detection/template_alignment.py` | Refactor | OpenCV | synthetic transform and real-form tests |
| Page preprocessing and crop quality | Full image-quality routing evidence | Deterministic assessment implemented; DB/event propagation remains | High | `packages/image_quality` | New | OpenCV | bounds, degraded-image, routing tests |
| Common OCR candidate contract | RapidOCR-first unified provider layer | Contract exists; RapidOCR ONNX provider and strict full-page guard missing | Critical | `packages/ocr`, `workers/field_candidates` | Refactor | RapidOCR, ONNX Runtime | provider conformance and standard-form crop-only tests |
| Paddle/Tesseract/cascade adapters | Selective field-specific secondary OCR | Policies are split across workers | High | `workers/cascade`, `config/` | Refactor | OCR runtimes | unresolved-only invocation tests |
| Candidate reconciliation and evidence | Platform-wide machine-readable reconciliation | Contracts and rationale vocabulary need consolidation | Critical | `workers/field_candidates`, `workers/cascade` | Refactor | validation rules | C3 false-acceptance tests |
| Deterministic healthcare validators | NPI/ICD/CPT/dates and financial consistency | ZIP/state, eligibility and broader cross-field rules incomplete | High | `packages/validation_rules` | Extend | reference snapshots | mutation/property and golden tests |
| Reference enrichment/providers | Versioned authoritative multi-attribute evidence | Snapshot/checksum governance incomplete | Critical | `packages/reference_enrichment` | Refactor | approved data sources | conflict and stale-source tests |
| Docling candidate provider | Difficult-table-only Docling route | Route eligibility and cost evidence need central enforcement | Medium | `workers/field_candidates/docling_provider.py` | Refactor | Docling | no-call common-path tests |
| VLM crop fallback and model router | Central Gemini/Vertex/Textract AI gateway | Provider-neutral PHI/budget/circuit-breaker gateway missing | Critical | `packages/ai_gateway` | New | Vertex AI, AWS | PHI denial, budget, timeout, schema tests |
| HITL API/UI and correction memory | Field-level review and trusted labels | React migration and label governance remain partial | High | `apps/human_review_api`, `apps/evaluation_ui` | Refactor | React stack | RBAC, concurrency, audit tests |
| Prometheus/OTel/Grafana assets | Accuracy/cost/model dashboards | Field/model cost and calibration drift panels incomplete | Medium | `packages/observability`, `deploy/monitoring` | Extend | Prometheus/Grafana | metric cardinality and dashboard validation |
| S3 wrapper, RBAC, malware scan, retention | Healthcare PHI production controls | KMS, tenant isolation, regional egress and audit verification incomplete | Critical | `packages/security`, `packages/storage`, `deploy/` | Extend | KMS/IAM/network policy | tenant escape and encryption tests |
| Performance harness | 5,000 docs/day, 50,000 pages/day, 10x burst | No verified representative load report | Critical | `tests/performance`, `evaluation/` | Extend | production-like corpus | soak, burst, recovery and cost tests |

## Reuse decisions

Retain the monorepo, Pydantic domain layer, event abstraction/outbox, object-store abstraction,
template registry, field candidates, deterministic validation, evidence manifest, HITL services,
and observability foundation. Refactor provider/routing seams incrementally. Do not introduce a
second event model, candidate model, review service, or storage abstraction.

## Phase 0 baseline

The repository has broad unit coverage and real-dataset marked tests. Existing generated reports
are not treated as fresh benchmarks. Phase 1 targeted verification is recorded in the implementation
plan; throughput, accuracy and cost remain `NOT TESTED` until run on a versioned representative set.
