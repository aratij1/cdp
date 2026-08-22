# CDP optimization gap analysis

Status date: 2026-08-22. Baseline is the governed development evaluation, not a production claim.

| Capability | Current state / repository location | Target and gap | Severity | Action | Expected effect | Required proof |
|---|---|---|---|---|---|---|
| Template registry | Versioned YAML registry and integrity-checked CMS package (`packages/templates`, `templates/cms1500`) | Add an official UB-04 package; CMS CDN currently blocks automated retrieval | High | Build, then operator approve | Registration and crop accuracy up | Package integrity and distorted-page tests |
| Registration | SIFT/FLANN/RANSAC fallback with measured quality (`workers/page_detection/template_alignment.py`) | Calibrate thresholds per form/scanner | High | Reuse + tune | Accuracy up; false crops down | Rotation/scale/translation/photocopy benchmark |
| Field coordinates | CMS-1500 and UB-04 versioned regions (`config/templates`) | Validate every UB locator against authoritative blank | High | Audit | UB accuracy up | Overlay review and golden crops |
| OCR engines | RapidOCR, PaddleOCR and Tesseract adapters | Route by measured value, not availability alone | Medium | Tune | Review/cost down | Engine-by-field ablation |
| Reconciliation | Consensus and candidate evidence retained | Learn field-specific disagreement policy | High | Refactor | Accuracy and STP up | False-accept constrained experiment |
| Validation | Format, semantic and cross-field rules | Expand payer-specific governed rules | Medium | Extend | Review down | Positive/negative fixtures |
| Reference matching | Governed exact/fuzzy matching with provenance | Add representative provider/payer masters | High | Integrate | Critical accuracy up | Time-split leakage audit |
| Evidence router | Deterministic escalation and evidence budget | Calibrate marginal-value thresholds | Medium | Tune | Processing cost down | Accuracy/cost Pareto |
| Unstructured documents | Separate fallback route | Add governed layout/document models | Medium | Extend | Coverage up | Per-document-type holdout |
| UB-04 | 22 service rows, extraction and error analysis | Official canonical image and locator validation absent | Critical | Build | Largest expected accuracy gain | UB-only distortion/field suite |
| HITL | Reason-coded review and immutable governance | Workflow timing and correction analytics need production data | High | Instrument | Review cost down | Reviewer agreement/time study |
| Kafka | Event contracts and consumers implemented | Sustained replay/backpressure proof absent | Medium | Verify | Scale confidence | Soak and recovery test |
| PostgreSQL | Durable repositories/migrations | Production HA and restore proof absent | High | Verify | Reliability | Restore/DR drill |
| Redis | Cache/idempotency support | Eviction/failover characterization absent | Medium | Verify | Latency stability | Failure injection |
| MinIO | Object evidence storage | Retention/encryption lifecycle proof absent | High | Verify | Compliance | Policy and restore test |
| Kubernetes | Manifests/health probes/resources present | Target-cluster validation absent | High | Verify | Operability | Staging deployment |
| KEDA | Autoscaling definitions present | Real queue-depth response unmeasured | High | Verify | Throughput/cost | Ramp and scale-to-zero test |
| Prometheus | Metrics instrumentation present | SLO alert validation incomplete | Medium | Tune | Faster detection | Alert simulation |
| OpenTelemetry | Trace hooks present | End-to-end sampling/export proof absent | Medium | Verify | Diagnosis | Trace continuity test |
| Grafana | Dashboards present | Operator acceptance and runbook linkage incomplete | Low | Refine | Operations | Dashboard acceptance |

Measured baseline: overall field accuracy 72.13%, development split 77.05%, CMS-1500 87.33%, UB-04 75.93%, critical-field accuracy 65.56%, false accepts 0, STP 0%, and claim review 76.67%. These figures are development evidence and cannot be promoted to production until an external, non-synthetic holdout passes.

The immediate order is: obtain/approve the official UB-04 blank, validate geometry overlays, calibrate registration on distortion strata, then run candidate experiments through the append-only ledger in `packages/experiment_ledger.py`. A candidate is rejected if false accepts or critical-field accuracy regress.
