# IDP Claims Platform

A hybrid, event-driven document-processing platform for healthcare claims:
machine-printed CMS-1500 (single page and multipage bundles with
attachments), UB claim forms, and unstructured claim documents — decoded,
classified, extracted, validated, and rendered to fixed-width NSF/UB92
output with full field-level evidence.

This repository is being built phase by phase (see
`docs/IMPLEMENTATION_PLAN.md`). **This README reflects what is actually
implemented today, not the end-state design** — the end-state architecture
lives in `docs/ARCHITECTURE.md`.

## What's implemented (Phase 1)

- Dataset inspection of the supplied `Images & Output.zip` sample —
  findings in `docs/DATASET_FINDINGS.md`.
- Canonical domain model (`packages/domain`), event envelope + topic
  registry + Kafka-compatible bus abstraction + outbox pattern
  (`packages/events`).
- Magic-byte file-type detection, SHA-256 + perceptual hashing, S3/MinIO
  object storage (`packages/storage`).
- TIFF (including multipage Group-4/T.6) and PDF decode, orientation,
  deskew, denoise, optional contrast enhancement, thumbnailing
  (`workers/document_preparation`), verified against the real supplied
  dataset.
- Ingestion API: upload, batch-directory intake, dedup, idempotency,
  malware-scan interface, outbox → `document.received`
  (`apps/ingestion_api`).
- Document-preparation worker: consumes `document.received`, decodes +
  preprocesses every page, persists them, outbox → `document.prepared`
  (`workers/document_preparation/consumer.py`) — a real, separate process
  connected only through the event bus.
- Docker Compose foundation: Postgres, Redis, MinIO, Redpanda
  (Kafka-protocol compatible), the ingestion API, and the
  document-preparation worker.
- Real Docker Compose validation: all 30 sample documents (Groups A–D)
  ingested and processed end-to-end through the live stack with correct
  page counts; two real concurrency bugs found under load and fixed (a
  Postgres schema-creation race between services, and an asyncio
  event-loop-starvation bug in the prep worker) — see git history / this
  section's "known simplifications" for what's still rough.

## What's implemented (Phase 2)

- Versioned template registry (`packages/templates`) with **real**
  CMS-1500 (NUCC 02/12) and UB-04 (CMS-1450) field-region definitions
  (`config/templates/*.yaml`), calibrated by visually inspecting real
  sample scans from the dataset (see `docs/DATASET_FINDINGS.md`).
- OpenCV-only (no OCR needed) page-structure signals, validated against
  the real dataset: grid/layout signature (morphological line-density
  fingerprint) and ORB feature-matching/homography alignment
  (`workers/page_detection`) — same-form scans measurably align/match
  better than different-form scans on the actual TIFFs.
- Anchor-phrase matching, decoupled from any OCR engine via a
  `TextExtractor` protocol; the real adapter
  (`PaddleOCRTextExtractor`) imports `paddleocr` lazily since
  `paddlepaddle` has no wheel for every dev host (confirmed on this
  project's host) — routing logic is fully unit-tested with a fake.
- Full Bundle A/B/C/D page-routing decision logic
  (`workers/page_detection/router.py`): anchor phrases → grid signature →
  template similarity → MobileNetV3 fallback (interface only, not
  trained) → human review, exactly the escalation order in
  `docs/ARCHITECTURE.md` §9. Bundle B explicitly marks every non-selected
  page `ATTACHMENT` (never extracted) so page preservation is auditable.
- Regional CMS-1500/UB-04 extraction (`workers/standard_form_extraction`):
  OCR runs **only** on configured field/service-line regions — structurally
  enforced (the extractor never calls whole-page OCR) and covered by a
  test that fails if it ever does. Field-type normalization (date/currency/
  NPI/tax-ID/code/checkbox) and service-line row extraction (stops at the
  first blank row) are implemented and tested.
- 101 passing unit tests, full `ruff` lint clean.

## What's implemented (Phase 3)

- Config-driven fixed-width engine (`packages/fixed_width`): spec model
  matching the required schema exactly (`record_type/field_name/
  start_position/length/alignment/padding_character/data_type/format/
  required/default/source_field`), a writer, a reader (the inverse), and
  a structural validator (gap/overlap/length checks).
- **Real, byte-verified NSF and UB92 record specs**
  (`config/output_specs/{nsf,ub92}/*.yaml`): NSF `AA0`/`BA0`/`BA1`/`CA0`
  and UB92 `01`, transcribed field-by-field from the supplied
  `NSF Matrix Version 2 15 - June 2013.doc` / `UB92 File Specs - February
  2012.doc`. Golden tests (`tests/golden`) parse every matching real
  reference-output line across Groups A/B/C/D, re-render it, and assert
  byte-for-byte identity — this is what caught a couple of position
  transcription slips before they became silent bugs. The remaining ~21
  record types (NSF `DA0`/`DA2`/`EA0`/`EK0`/`FA0`/`HA0`/`XA0`/`YA0`/`ZA0`;
  UB92 `10`/`20`/`30`/`31`/`40`/`46`/`60`/`70`/`80`/`90`/`95`/`99`) are
  **not transcribed yet** — same mechanism, more data entry (see
  docs/IMPLEMENTATION_PLAN.md).
- Deterministic validators (`packages/validation_rules`), field-scoped,
  never a single document-level score: NPI Luhn checksum (verified
  against the real provider NPI in the dataset), ICD-10/CPT/HCPCS syntax
  (verified against real diagnosis/procedure codes in the dataset) with
  an optional reference-adapter extension point, modifier syntax, date
  relationships, non-negative currency/positive units, required-field
  checks, and service-line-total ↔ claim-total reconciliation.
  `ThresholdRegistry` loads criticality-aware per-field confidence
  thresholds from `config/validation/*.yaml` (real configs for both
  templates); `ValidationEngine` ties it all together against a
  canonical `Claim`.
- Output generation (`workers/output_generation`): canonical JSON
  (complete — every `Claim` field), an evidence manifest (page/bbox/
  confidence/method per field), a reconciliation report, and an NSF
  writer that resolves claim data through `source_field` for whichever
  record types are currently configured (see the honest scope note in
  `nsf_output.py` — it does not yet produce a complete, submittable NSF
  file). X12 837 is an interface only (`UnimplementedX12_837Adapter`) —
  no sample 837 output was supplied to validate against.
- 170 passing tests (unit + golden), full `ruff` lint clean.

## What's implemented (Phase 4)

- Hybrid model router (`packages/model_router`): a pure decision function
  (no model calls) implementing the full escalation order —
  cache → template rules/OpenCV alignment/regional PaddleOCR (assumed
  already attempted before the router is invoked) → alternate
  preprocessing/OCR → Table Transformer (table fields) / LayoutLMv3
  (unstructured documents) → compact VLM (only if enabled *and* every
  cheaper stage already failed) → human review. Accepts field
  criticality/OCR confidence/validation failures/OCR disagreement/table
  or unstructured-document flags; returns `selected_route`, `reason_codes`,
  `estimated_cost_usd`, `escalation_count`. A dedicated test walks the
  full ladder step-by-step and confirms the VLM is never reached with it
  disabled.
- OCR retry (`workers/retry`): alternate preprocessing presets (upscale,
  aggressive contrast, binarize+sharpen — deliberately different from the
  Phase 1 defaults) applied to exactly one failed field's crop, never a
  whole page; keeps whichever preset's OCR result beats the original
  confidence.
- VLM fallback (`workers/vlm_fallback`): a real adapter
  (`OpenAIVLLMAdapter`) over a vLLM-compatible OpenAI `/chat/completions`
  endpoint — temperature 0, strict JSON schema with
  `additionalProperties: false`, crop-only image input, rejects any
  unrequested field name in the response, preserves `insufficient_evidence`
  instead of fabricating a value, and raises before any HTTP call when
  disabled. `VLMFallbackService` enforces "failed fields only" and "flows
  through the same validation as any other extraction" one layer up.
  Tested end-to-end against a mocked HTTP transport (no real vLLM
  server involved) — inspects the actual outgoing request payload to
  verify temperature/schema/crop-only claims, not just the parsed result.
- LayoutLMv3 and Table Transformer adapter interfaces
  (`workers/unstructured_extraction`) — same lazy-import,
  `ModelNotAvailableError`-until-configured pattern as MobileNetV3/
  PaddleOCR; not trained/wired.
- 201 passing tests, full `ruff` lint clean.

## What's implemented (Phase 5)

- Observability (`packages/observability`): every Prometheus metric named
  in the platform spec, exposed at `/metrics` on both `ingestion-api` and
  `human-review-api` (`prometheus_client` + a shared `CollectorRegistry`);
  an OpenTelemetry tracer/span helper; and `configure_logging()` — PHI
  redaction (below) wired into `structlog` and actually called from every
  app/worker entrypoint, not left as an unused utility.
- Security (`packages/security`): structured PHI redaction (masks known
  PHI-risk *keys* recursively through nested log data, proven end-to-end
  through the real rendered log line, not just the standalone function);
  RBAC hooks (`Role`/`Permission` model + a FastAPI dependency reading an
  `X-User-Role` header — a hook, not a full identity provider, by design);
  and a retention/deletion workflow (`RetentionService`, tested against
  fakes, with real `DocumentRepository.find_received_before`/`.delete()`
  and `ObjectStore.delete_object()` implementations wired in). Signed
  object-store URLs were already in Phase 1
  (`ObjectStore.signed_get_url`) — now actually used, by the review API.
- Human review API + server-rendered UI (`apps/human_review_api`): lists
  and serves **only failed fields**, never a whole claim; every
  correction/rejection persists reviewer/timestamp/previous-value/
  new-value/reason (`FieldCorrection`) and emits an immutable `AuditEvent`.
  The UI is plain server-rendered HTML (no build step), with every
  reviewer-facing and reviewer-submitted value passed through `html.escape`
  (tested against actual XSS payloads, not just trusted-input happy paths).
- Helm charts for the three deployables with a real running entrypoint
  (`ingestion-api`, `human-review-api`, `document-preparation-worker`),
  validated with a real `helm` binary (`helm lint` + `helm template`, not
  just written and hoped) — see `deploy/helm/README.md`.
- KEDA `ScaledObject`s for all five worker pools from the spec (CPU
  preprocessing, CPU OCR, GPU OCR/layout, VLM, output generation) —
  YAML-structure-validated; only the CPU-preprocessing one targets a
  Deployment that exists today (see `deploy/keda/README.md` for which
  pools are still ahead of their worker's own consumer entrypoint).
- Monitoring config (`deploy/monitoring`): Prometheus scrape config, 6
  alert rules (including a tripwire that fires if the VLM is ever invoked
  while `VLM_ENABLED=false`), and a 7-panel Grafana dashboard.
- Performance harness (`tests/performance`), run against all 30 real
  sample files: measured real numbers for TIFF decode and full
  decode+preprocess throughput/latency, and grid-signature computation;
  clearly-labeled-as-illustrative (not measured) cost-per-page projection.
  **This harness found a real bug**: the default pipeline was running
  `cv2.fastNlMeansDenoising` unconditionally on every page (~8.5s on a
  real full-resolution scan) and PNG-encoding every persisted transform
  with `optimize=True` (an expensive compression search) — together the
  dominant cost, at 0.15 pages/sec end-to-end. Both are now fixed (a
  cheaper `medianBlur` default, `fastNlMeansDenoising` moved to the
  OCR-retry path where it only ever runs on a small crop; `optimize=False`
  for PNG encoding) — **9x faster, 1.34 pages/sec**, with the expensive
  denoiser still available exactly where it's worth its cost.
- 231 passing tests, full `ruff` lint clean.

## What's implemented (Phase 6)

- Real OCR wired into a running pipeline for the first time. Both adapters
  (`PaddleOCRTextExtractor`, `workers/page_detection/text_extraction.py`)
  were always real code, not stubs — they just had no consumer calling
  them and no image with the `[ml]` extras installed to run in. This phase
  adds both:
  - `deploy/docker/ocr.Dockerfile` — a lighter image than the eventual
    full `[ml]` one, built off a new `[ocr]` extras group
    (`paddleocr`/`paddlepaddle` only, no `torch`/`transformers`) since
    neither new worker below touches LayoutLMv3/Table Transformer/VLM.
  - `workers/page_detection/consumer.py` — consumes `document.prepared`,
    runs real PaddleOCR anchor-phrase classification (and grid-signature/
    alignment fallback, when configured) via the already-tested
    `PageRoutingService`, persists a `PageClassification` row per page
    (new `page_classifications` table — the confidence/method/
    reason_codes detail that `PageORM.role` alone couldn't hold) and the
    resolved `PageORM.role`, updates the document's `bundle_type`/
    `status`, and outboxes `page.selected` (always) plus
    `extraction.standard.requested` (when a page was confidently matched
    to a template).
  - `workers/standard_form_extraction/consumer.py` — consumes
    `extraction.standard.requested`, runs real regional PaddleOCR via the
    already-tested `StandardFormExtractionService` against the selected
    page (rescaled to the template's `reference_dimensions` — see the
    known simplification below), persists every `ExtractedField` (new
    `extracted_fields` table, header fields and service-line cells alike,
    distinguished by a nullable `service_line_number` column), and
    outboxes `extraction.completed`.
  - Both wired into `docker-compose.yml` as real services
    (`page-detection-worker`, `standard-form-extraction-worker`), and into
    the previously-unused `pages_processed_total`/`attachments_skipped_total`/
    `classification_latency_seconds`/`ocr_latency_seconds` Prometheus
    metrics (defined since Phase 5, never actually incremented anywhere
    until now).
  - VLM stays disabled/unwired by explicit choice — `PaddleOCR` alone
    resolves anchor/region matches deterministically for these two
    stages; wiring the VLM escalation path (`workers/vlm_fallback`) is a
    separate follow-up, same as the router/retry/validation worker gap
    noted below.
- 6 new tests (repository round-trips + both consumers' `handle_one`
  end-to-end against fakes, mirroring `test_document_preparation_worker.py`'s
  pattern), 237 passing tests total, still lint-clean.

## Not yet implemented

Every package/worker stub below raises on use and is not wired into a
running pipeline yet — see `docs/IMPLEMENTATION_PLAN.md` for the phase each
lands in:

| Area | Phase | Notes |
|---|---|---|
| Bundle D's own extraction worker (PaddleOCR + configured schema) | 2/4 | `workers/unstructured_extraction` has adapter interfaces only, no orchestrating worker yet |
| LayoutLMv3 / Table Transformer inference | 2/4 | interfaces exist, no trained checkpoint |
| MobileNetV3 page-classification fallback | 2/4 | interface exists (`workers/page_detection/mobilenet_classifier.py`), no trained checkpoint |
| Remaining NSF/UB92 record types (~21 of ~26) | 3 | `config/output_specs/{nsf,ub92}` — same transcription mechanism as AA0/BA0/BA1/CA0/01, not yet done |
| EA0/FA0-driven full NSF claim+service-line output | 3 | `workers/output_generation/nsf_output.py` currently covers only the batch/patient header records |
| ICD-10/CPT/HCPCS reference-table lookups | 3 | syntax validation only today; `NoOp*ReferenceAdapter` is the default |
| X12 837 output | 3 | interface only, `UnimplementedX12_837Adapter` — no sample 837 output supplied |
| Full auth (RBAC currently reads an `X-User-Role` header) | 5 | `packages/security/fastapi_rbac.py` is an explicit hook, not an identity provider — see its docstring for the one function to replace |
| Helm/KEDA against a real cluster | 5 | charts/ScaledObjects are validated with real tooling (`helm lint`/`template`; YAML-structure checks) but never `helm install`ed or applied — no Kubernetes cluster or KEDA installation available in this environment |
| Remaining worker Helm charts | 5/6 | `page_detection`, `standard_form_extraction`, `unstructured_extraction`, `validation`, `retry`, `vlm_fallback`, `output_generation` have no chart yet, even though the first two now have real consumer entrypoints and a KEDA `ScaledObject` (Phase 6) — same reason as the KEDA row above them in `deploy/keda/README.md` |

Known simplifications (see `docs/ARCHITECTURE.md` for rationale):
- `apps/ingestion_api/db` is shared by `apps.ingestion_api` and
  `workers.document_preparation` in Phase 1 (one "documents" bounded
  context, not yet split per-service).
- Orientation detection is a projection-profile heuristic, not a trained
  OSD model — documented in `workers/document_preparation/preprocessing.py`.
- The outbox relay uses a synchronous SQLAlchemy session per poll; moving
  to async SQLAlchemy (asyncpg) later is a drop-in change behind the same
  `OutboxRepository` protocol.
- Template field regions (`config/templates/*.yaml`) are coarse, box-level
  estimates from visually inspecting one real scan per form — not a
  pixel-perfect production calibration; OpenCV alignment plus generous
  region padding is what makes this tolerable, not precision authoring.
- The Bundle B/D page-routing escalation thresholds
  (`workers/page_detection/router.py`) are initial values validated
  directionally against the real dataset, not tuned against a labeled
  precision/recall set.
- NSF mixes claim-scoped data (patient, in `CA0`) with batch/submission-
  scoped data (submitter identity in `AA0`, batch number in `BA0`/`BA1`)
  that doesn't belong on a single `Claim` — `NSFOutputWriter` takes that
  as an explicit `batch_context` parameter rather than inventing a
  `Batch`/`Submission` domain aggregate prematurely.
- `resolve_source_field` (`packages/fixed_width/resolver.py`) only walks
  simple dotted attribute paths, not list-indexed ones — sufficient for
  today's header-record specs; service-line-level records (NSF `FA0`,
  UB92 `60`) will need `service_lines[i].field`-style paths when those
  record types are transcribed.
- PHI redaction (`packages/security/redaction.py`) is key-name-based
  ("does this field name look like it holds PHI"), not content-based —
  deliberately, since scanning free text for PHI patterns is unreliable
  and out of scope; it means a key not on the list whose *value* happens
  to contain PHI (e.g. a stray free-text `notes` field) would not be
  caught. Extend `PHI_KEY_MARKERS` rather than trying to add pattern
  matching.
- `RetentionService`/`DocumentRepository.find_received_before`/`.delete()`
  are tested against fakes and SQLite respectively — not yet exercised
  against a real Postgres instance or wired into a scheduled job (a cron
  Helm chart or similar); running `run_retention_sweep` is a manual/
  scripted operation today.
- Real ORB/homography alignment (`workers.page_detection.template_alignment`)
  and grid-signature matching need a reference *image* of a blank/
  representative form, and no such asset ships in this repository (the
  only real scans available are the gitignored sample dataset, never
  committed). This is now an **opt-in operator calibration step**, the
  same pattern as `VLM_ENABLED`: set `reference_image_path` on a template's
  YAML (`config/templates/*.yaml`) to a real scan dropped under the
  gitignored `config/templates/reference_images/` directory, and both
  workers pick it up automatically —
  `workers/standard_form_extraction/consumer.py` warps the selected page
  into true alignment before regional OCR instead of only rescaling it to
  `reference_dimensions`, and `PageRoutingService` (wired in
  `page_detection/consumer.py`) gains the grid-signature/ORB-alignment
  escalation steps instead of relying on anchor-phrase matching alone.
  Verified empirically against the local (gitignored) sample dataset: a
  *synthetically rendered* reference (drawn from the template's field
  regions) does **not** work (ORB score ~0.06, grid similarity ~0.5, both
  well under the routing thresholds) — a real reference scan is required;
  synthetic references are not a substitute. Without a configured
  reference image (the default), both workers behave exactly as before:
  rescale-only extraction and anchor-phrase-only routing.
- Bundle D (`workers/unstructured_extraction`) and non-selected Bundle B/D
  pages have no extraction worker yet (see the table above), so
  `page_detection/consumer.py` classifies them correctly but nothing
  downstream ever processes them further today.

## Repository layout

```
apps/                 deployable HTTP services
  ingestion_api/       upload, batch intake, dedup, outbox (Phase 1)
  human_review_api/    failed-field review (Phase 5)
  output_api/          fixed-width/JSON/X12 retrieval (Phase 3/5)
workers/               deployable Kafka consumers
  document_preparation/  decode, preprocess (Phase 1)
  page_detection/         Bundle A/B/C/D routing (Phase 2)
  standard_form_extraction/  CMS-1500/UB regional OCR (Phase 2)
  unstructured_extraction/   Bundle D schemas, LayoutLMv3 (Phase 2/4)
  validation/             deterministic validation (Phase 3)
  retry/                  alternate preprocessing/OCR (Phase 4)
  vlm_fallback/           compact VLM adapter (Phase 4)
  output_generation/      fixed-width/JSON/X12 (Phase 3)
packages/              shared libraries, no service should duplicate these
  domain/    events/    storage/   observability/  security/
  templates/ validation_rules/     fixed_width/     model_router/
config/                data-driven config (templates, validation, output specs)
tests/                 unit / integration / golden / performance
deploy/                docker / helm / keda / monitoring
docs/                  findings, architecture decisions, implementation plan
dataset_raw/           extracted sample dataset (gitignored, see below)
```

The ownership rules and enforced dependency direction are documented in
[`docs/REPOSITORY_STRUCTURE.md`](docs/REPOSITORY_STRUCTURE.md).
Deployment authorization and the remaining operational blockers are tracked in
[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

## Setup

Requires Python 3.11+, Docker, and Docker Compose.

```bash
make setup     # copies .env.example -> .env, pip installs the project (+ dev extras)
make test      # unit tests, no Docker required
make quality   # architecture checks, lint, and unit tests
make run       # docker compose up: Postgres, Redis, MinIO, Redpanda, ingestion API, prep/page-detection/extraction workers, review API
make test-integration   # brings the stack up, runs tests/integration, tears it down
```

`make clean` removes only reproducible test/build caches. It preserves Docker
volumes, datasets, evaluation results, and model caches. Use the explicitly
destructive `make clean-runtime-data` target when local service volumes must be
removed.

`make run` exposes:
- Ingestion API docs: http://localhost:8000/docs
- Human review UI: http://localhost:8100/ui/review-tasks (host port 8100 —
  the container listens on 8001 internally; host 8001 was already bound by
  an unrelated container on the dev machine this was built on)
- MinIO console: http://localhost:9001 (`minioadmin` / `minioadmin`)
- Redpanda admin: http://localhost:9644

### The sample dataset

The supplied `Images & Output.zip` is **not committed** (see
`docs/DATASET_FINDINGS.md` for why — it contains realistic-looking
patient/provider data with no confirmation it's synthetic). To reproduce
the dataset-backed tests locally:

1. Extract the zip to `dataset_raw/` at the repo root (git-ignored).
2. `pytest tests/unit -q` — tests tagged `requires_dataset` run
   automatically when `dataset_raw/` is present, and are skipped
   otherwise.
3. `python -m apps.ingestion_api.batch_ingest dataset_raw --tenant-id demo`
   to batch-ingest the whole sample set through the running API's database
   (requires `make run` first).

All committed test fixtures (`tests/golden/fixtures/`) are hand-built
synthetic look-alikes, never copies of the supplied dataset.

## Testing

- `tests/unit` — no external services required (SQLite in-memory DB, an
  in-memory `ObjectStore` test double, `InMemoryEventBus`). This is what CI
  runs on every change.
- `tests/integration` — requires the compose stack (`make test-integration`);
  auto-skips if the ingestion API isn't reachable, so it never blocks
  `make test`.
- `tests/golden` — byte-for-byte fixed-width output comparisons against
  the real supplied reference `.txt` files, for the NSF/UB92 record types
  currently transcribed (`requires_dataset`-gated, like the Phase 1/2
  real-data tests). Run explicitly with `pytest tests/golden -m golden`.
- `tests/performance` — throughput/latency harness (Phase 5), not part of
  normal test runs (`pytest -m performance`).

## Operational notes

- **PHI**: never logged, traced, or included in metrics by design (audit
  events store field *names* and IDs, not values). `packages/security`
  gets full redaction/RBAC wiring in Phase 5.
- **VLM**: `VLM_ENABLED=false` by default (`.env.example`). The pipeline is
  designed to run fully without it — see the hybrid router escalation
  order in `docs/ARCHITECTURE.md` §9.
- **No document bytes in Kafka**: enforced at the type level —
  `EventEnvelope.assert_no_bytes_payload()` rejects any `bytes` value
  anywhere in a payload before publish.

See `docs/DATASET_FINDINGS.md`, `docs/ARCHITECTURE.md`, and
`docs/IMPLEMENTATION_PLAN.md` for the full detail behind each of the above.

### Controlled-disposition OCR cascade

Field OCR uses the shared `OCRRequest`/`OCRCandidate` contract and retains
engine, model/version, preprocessing, confidence, box, latency, validation,
and evidence metadata. The runtime route is primary PaddleOCR, selected
field-crop preprocessing, field-configured Tesseract, TrOCR for handwriting
or mixed crops, optional crop-only VLM/cloud, then review.

Raw confidence is never sufficient for critical fields. Hard validation must
pass and critical values require either two independent agreeing engines or
an authoritative reference match. Otherwise the disposition is
`HUMAN_REVIEW_REQUIRED`. A claim can finalize only when every critical field
is `VALIDATED_AUTOMATICALLY` or `VERIFIED_BY_HUMAN`.

Optional model runtimes:

```powershell
docker compose --profile ml build handwriting-ocr
docker compose --profile ppocr-v5 build ppocr-v5
```

The live governed comparison report is served at
`http://localhost:8180/reports/comparison.html`. Rebuild it after an evaluation
with `python -m evaluation.current_comparison_report`; its summary cards poll
the latest JSON metrics every 15 seconds. The atomic baseline remains at
`http://localhost:8180/reports/atomic_comparison.html`. The current baseline
is not a claim of 100% automated OCR. Reports identify their calibration,
validation, holdout, or synthetic split.

### Docker-free evaluation and active learning

The offline benchmark requires no Kafka, Postgres, MinIO, or API:

```powershell
python -m evaluation.run_fixed_family_ocr

python -m evaluation.offline_pipeline `
  --predictions evaluation_data/predictions_fixed_family.json `
  --output evaluation_results/offline_benchmark
```

Add `--run-inference` in a Python 3.11 OCR environment to rebuild crops and
execute the local engines. Cached evaluation remains runnable on developer
machines without PaddleOCR.

Generate the error Pareto and review dataset:

```powershell
python -m evaluation.error_backlog `
  --ground-truth evaluation_data/ground_truth.json `
  --predictions evaluation_data/predictions_fixed_family.json `
  --output evaluation_results/error_backlog

python -m evaluation.export_review_dataset `
  --predictions evaluation_data/predictions_fixed_family.json `
  --output evaluation_results/review_queue/manifest.jsonl
```

Review examples are split deterministically by document, never randomly by
crop. Ground truth is consumed only by evaluation commands and is prohibited
as an inference-time reference source.
