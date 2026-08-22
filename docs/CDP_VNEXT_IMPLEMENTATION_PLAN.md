# CDP vNext Implementation Plan and Backlog

## Acceptance discipline

Each phase must preserve raw artifacts, emit machine-readable evidence, fail closed for critical
fields, pass its targeted unit/integration tests, and publish measured rather than fabricated
accuracy, latency and cost results.

| Epic | Feature / task | Repository path | Dependencies | Risk | Acceptance criteria | Tests |
|---|---|---|---|---|---|---|
| Phase 0 | Freeze representative baseline and evaluation manifest | `evaluation/`, `tests/golden` | approved labels | label leakage | immutable dataset/version and per-field baseline | leakage, golden, repeatability |
| Phase 1 | Image-quality evidence | `packages/image_quality` | OpenCV | heuristic drift | bounded metrics and reason codes for every decoded page | clean/degraded synthetic and corpus distributions |
| Phase 1 | Adaptive registration and evidence | `workers/page_detection/template_alignment.py`, `packages/domain/registration.py` | OpenCV SIFT | wrong-template acceptance | cheap short-circuit; SIFT/FLANN/Lowe/RANSAC fallback; configurable gates | translation, perspective, blank, cross-form, real-form |
| Phase 1 | Persist quality/registration evidence | DB migrations and page events | SQLAlchemy/Alembic | schema compatibility | evidence queryable by document/page/template/version | migration and event round-trip |
| Phase 2 | Unified OCR providers and RapidOCR primary | `packages/ocr` | RapidOCR/ONNX | runtime footprint | normalized candidates; CPU provider; crop-only standard forms | conformance and full-page denial |
| Phase 2 | Field preprocessing/tournaments | `packages/preprocessing`, `config/` | OpenCV | combinatorial cost | at most configured variants on unresolved fields | policy and invocation-count tests |
| Phase 3 | Reconciliation, calibration, C0-C3 policy | `packages/candidate_reconciliation`, `packages/confidence` | sklearn or small model runtime | unsafe calibration | C3 cannot accept from single probabilistic source | adversarial and calibration tests |
| Phase 3 | Reference matching and healthcare rules | `packages/reference_enrichment`, `packages/validation_rules` | governed snapshots | false correction | raw/normalized/corrected/final provenance retained | conflicts, checksum, cross-field tests |
| Phase 4 | Central AI gateway and selective Docling/Gemini/Textract | `packages/ai_gateway`, providers | Vertex/AWS/Docling | PHI/cost leakage | crop-only, allowlist, region, budget, audit, strict schema | mocked denial/fallback/circuit tests |
| Phase 5 | HITL feedback and governance | `apps/human_review_api`, `apps/evaluation_ui` | RBAC/Postgres | label poisoning | atomic review, append-only audit, trusted export gates | auth, concurrency, audit tests |
| Phase 6 | Kubernetes/Helm/KEDA and observability | `deploy/` | cluster/Prometheus | scale instability | lag scaling, PDB, limits, network policy and dashboards | helm lint, burst, failure recovery |
| Phase 7 | Production qualification | `evaluation/`, `docs/` | representative corpus | unsupported claims | signed accuracy/cost/load/security reports and rollback drill | full release gate |

## Phase 1 implementation report

### Files changed

- `packages/domain/registration.py`
- `packages/image_quality/`
- `workers/page_detection/template_alignment.py`
- `tests/unit/cases/test_image_quality.py`
- `tests/unit/cases/test_template_alignment.py`

### Functionality implemented

- Cheap edge/geometry phase-correlation path with a strict confidence gate.
- SIFT descriptors, FLANN KNN, Lowe ratio filtering, RANSAC homography and perspective warp.
- Evidence for keypoints, candidate/good matches, inliers, ratio, reprojection error, coverage,
  homography quality, confidence, transform, timing, acceptance and rejection reason.
- Deterministic blur, contrast, brightness, skew, rotation, noise, DPI, compression artifact,
  clipping and text-density assessment with a versioned evidence contract.

### Test and benchmark status

Targeted tests use synthetic and repository real-form samples. Record the final command/result in
the change handoff. No accuracy, throughput or cost benchmark is claimed by this phase; those remain
`NOT TESTED` pending a versioned representative evaluation run.

### Known limitations / next phase

Quality and registration evidence are returned in memory but not yet persisted on page records or
propagated in events. Next, add the backward-compatible migration/event fields and route image-quality
signals into preprocessing and OCR selection before implementing RapidOCR.

## Phase 2 implementation report

### Functionality implemented

- Page image-quality and classification registration evidence persist as nullable JSON contracts.
- Page-selection and extraction-completion events expose the same versioned evidence.
- RapidOCR/ONNX is the primary standard-form regional OCR adapter, loaded lazily with CPU default.
- Unified asynchronous `OCRProvider.extract`/`OCRResult` contract normalizes provider output.
- CMS-1500 and UB-04 full-page RapidOCR is rejected unless registration failed or policy explicitly
  authorizes it. PaddleOCR remains available as a secondary engine.
- PostgreSQL migration and non-destructive rollback guidance are included.

### Acceptance status

Provider normalization, crop geometry, provenance, CPU default, full-page denial, persistence mapping,
document preparation, page routing and standard extraction are covered by targeted tests. Real OCR
accuracy and cost comparisons remain `NOT TESTED` until RapidOCR models are installed in the benchmark
worker and run against a governed labeled dataset.

## Phase 3 implementation report

### Functionality implemented

- Externalized C0-C3 criticality policy with fail-closed C3 behavior.
- Platform reconciliation result uses `ACCEPT`, `ESCALATE`, `ABSTAIN`, or `REVIEW`, evidence
  references, conflicts, candidate identifiers, calibration version and reason codes.
- Platt and isotonic calibration inference with field/engine/global registry resolution.
- Independent-engine families prevent variants of the same OCR family from double voting.
- C3 fields require independent engines or deterministic/authoritative evidence; raw OCR, calibrated
  OCR, Gemini, or other single-model confidence can never satisfy this requirement alone.

### Known limitations / next phase

Calibration training and artifact signing are not included; only safe versioned inference is present.
The next phase centralizes reference snapshots and the AI gateway, including tenant PHI, region,
budget, circuit-breaker and crop-only controls.

## Phase 4 implementation report

### Functionality implemented

- Central provider-neutral AI gateway with tenant enablement, model allowlists, PHI approval,
  approved-region enforcement, crop-size limits, daily budgets, per-minute limits, timeouts, bounded
  retries, circuit breaking, trace correlation and PHI-safe cost/token audit records.
- Crop bytes are content-address verified; full documents are structurally absent from the request.
- Vertex Gemini 2.5 Flash-Lite, Flash and Pro providers use temperature zero and strict structured
  output. AWS Textract uses `DetectDocumentText` and normalizes results to the same response contract.
- Cost/SLA-aware Gemini escalation never treats C3 AI confidence as sufficient for acceptance.
- Docling eligibility is limited to failed table extraction or table-heavy unstructured documents.

### Known limitations / next phase

Cloud transports are intentionally dependency-injected and require approved production composition
with workload identity. No live provider call, accuracy claim or price validation was performed.
Next: connect gateway outcomes to worker orchestration, HITL feedback and observability dashboards,
then qualify Kubernetes/KEDA scaling and recovery behavior.

## Phase 5 implementation report

### Functionality implemented

- Atomic compare-and-swap task claiming and optimistic versions prevent double assignment and stale
  decisions. Claimed tasks can only be corrected or rejected by their assignee.
- Correction/rejection and a PHI-safe append-only audit event commit in the same transaction. Audit
  records retain actor, version, reason, timestamp and decision hash, never the corrected value.
- First-pass corrections are excluded from training memory. Trusted labels require visible evidence,
  approved crop quality, deterministic validation, claim revalidation and an independent approver.
- Trusted-label JSONL export is hash chained so tampering, deletion and reordering are detectable.
- PostgreSQL migration and least-privilege guidance restrict audit storage to INSERT/SELECT.

### Known limitations / next phase

The current header-based role hook still requires replacement with the deployment identity provider.
No multi-reviewer usability or turnaround benchmark has been run. Next: Kubernetes/Helm/KEDA,
network policies, dashboards, queue-lag scaling and failure-recovery qualification.

## Phase 6 implementation report

### Functionality implemented

- One Helm worker-pool chart generates real Deployments and matching KEDA ScaledObjects from the same
  configuration, with 10x+ burst ceilings, bounded scale-up, stabilized scale-down and scaler fallback.
- Restricted non-root pods, read-only roots, dropped capabilities, seccomp, bounded ephemeral storage,
  disabled service-account token mounts, API disruption budgets and default-deny worker networking.
- Metrics and dashboards cover reconciliation decisions, critical false accepts, external AI cost and
  tokens, registration quality, image quality, review queues/turnaround and Kafka lag.
- Critical false acceptance, AI budget burn, C3 review backlog and sustained lag alerts were added.
- Deployment and failure/recovery runbooks document order, containment, rollback and recovery gates.

### Known limitations / next phase

Helm CLI and a Kubernetes cluster are unavailable in this environment, so live KEDA, CNI, PDB and
workload-identity behavior remain `NOT TESTED`; structural tests validate target completeness and
security settings. Phase 7 must run representative load, chaos, restore, accuracy and cost gates.
