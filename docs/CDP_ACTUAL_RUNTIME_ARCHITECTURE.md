# CDP Actual Runtime Architecture

## Canonical event flow

`document.received -> document.prepared -> page.selected -> extraction.standard.requested | extraction.unstructured.requested -> extraction.completed -> claim.validated -> output.completed`

The database repositories hold document, page, extracted-field, and claim state. The transactional outbox owns event publication. Object storage owns source/prepared page bytes. Event envelopes carry route, form identity, geometry, and lineage identifiers; they are not decision authorities.

## Five planes

### 1. Document plane

`workers/page_detection/consumer.py` consumes prepared pages, classifies and verifies form identity, chooses one `ProcessingRoute`, and emits exactly one standard or unstructured extraction request. `packages/document_routing/decision_service.py`, the taxonomy, and standard-form verification supply routing evidence. A verified CMS-1500 or UB-04 page may enter the standard path. Unknown structured and unknown unstructured pages enter Bundle D. Routing may select a worker; it may not accept a field or claim.

State: prepared page image, classification evidence, form identity, processing route, and extraction geometry request.

### 2. Extraction plane

#### CMS-1500

`StandardFormExtractionWorker -> StandardFormProcessingService -> PageObservationService -> CMS1500FieldGraph -> DynamicROIResolver -> StandardFormExtractionService`.

One full-page RapidOCR observation is cached by page hash/model/preprocessing version. CMS anchor/ownership evidence proposes field regions. The resolver selects dynamic regions. Existing observation tokens are used first; one regional RapidOCR read is allowed only when the candidate is insufficient. Registration/fixed ROI is a third-priority explicit fallback for unresolved dynamic fields and is fail-closed.

Input: verified identity, CMS template lineage, prepared image. Output: candidates, normalized candidate values, geometry/provenance, and diagnostic timing. Authority: candidate production only.

#### UB-04

`StandardFormExtractionWorker -> StandardFormProcessingService -> PageObservationService -> FieldLocator + UB04StructuralMapDetector -> DynamicROIResolver -> StandardFormExtractionService`.

UB service lines use `UB04ObservationServiceLineExtractor -> UB04ServiceLineEngine`. It reuses full-page token geometry and observed header columns; bounded HCPCS/unit regional OCR runs only for unresolved cells. The registered `UB04ServiceLineExtractor` remains an explicit fixed-template compatibility fallback.

Input/output authority is the same as CMS. Table reconstruction owns row and column candidate assignment, not claim acceptance.

#### Tier D / unstructured

`UnstructuredExtractionWorker -> full-page PaddleOCR -> DocumentFamilyRouter -> anchor crops` for known recurring families. If no known-family extraction is produced, `BundleDLayoutEngine` performs generic label/value extraction. Optional handwriting/VLM components collect field-crop candidates only.

The live consumer currently invokes `EvidenceDecisionService` during generic layout extraction and persists a disposition before validation. It uses the same decision class but crosses the extraction/decision boundary and creates a second decision site. The target architecture moves this call to validation and leaves Bundle D candidate-only.

### 3. Evidence plane

`DeterministicEvidenceService`, `ReferenceEvidenceService`, structural evidence, cross-field evidence, and OCR provenance feed a single `EvidenceBundle`. `EvidenceDependencyService` classifies correlated, partially independent, independent, or unknown lineage. Unknown provenance fails closed. Reference sources have explicit disabled, test-fixture, or authorized state.

This plane may describe evidence and dependency. It may not issue the final field disposition.

### 4. Decision plane

`workers/validation/consumer.py` is the canonical runtime decision site. `EvidenceDecisionService` is the sole machine field-disposition authority. It reconciles candidates, evaluates the evidence policy, and emits accept, escalate, insufficient-evidence, or review outcomes. `ClaimDecisionService` is the sole claim blocker/STP authority and consumes field decisions plus claim evidence. Retry requests are suggestions from the decision result, not independent acceptance decisions.

Final outputs are persisted field decisions, retry/review requests, claim blockers, and `claim.validated`.

### 5. Evaluation plane

`evaluation/phase8_1_golden.py` calls the production `StandardFormProcessingService`. `evaluation/phase8_10_extraction_recovery.py` reuses frozen observations, measures localization/extraction/table behavior, then calls the generalization policy replay.

Extraction implementation parity is `PASS`. End-to-end configuration parity is `FAIL`: `replay_source` explicitly constructs `EvidenceDecisionService(route_mode="evaluation")` with `evidence-policy-v4-dependency-aware-balanced`, whereas runtime validation constructs the default runtime service and `evidence-policy-v4-dependency-aware`. Phase 8.10's previous aggregate parity label is therefore too broad.

## Retry, fallback, latency, and cost

- Full-page observation cache key: page digest + OCR model version + preprocessing version.
- Regional OCR execution cache key: page/crop/profile/engine/version lineage.
- Dynamic CMS/UB localization is preferred; registered fixed geometry is explicit fallback; otherwise the page routes to unknown structured layout.
- Validation emits `field.retry.requested`; the retry worker calls the same evidence decision authority.
- Cloud is disabled on the common path. Measured cloud calls/cost are 0/$0.
- Fully loaded cost is dominated by modeled review labor: $0.3876/page mean reported by the frozen replay.
- Latency P50/P95/P99 by source is A 4.675/10.127/11.146 s, B 5.103/8.686/8.787 s, C 3.208/5.738/15.150 s. Stage CPU attribution was not persisted in the immutable Phase 8.10 result.

## Test ownership

Architecture tests enforce visual-evidence authority. Integration tests cover deterministic, router, field-decision, and claim-decision parity. Unit tests cover standard extraction, UB tables, evidence semantics, and claim decisions. The missing test is a single manifest asserting runtime and evaluation use identical policy/route/config identities; that absence allowed the aggregate parity false positive.
