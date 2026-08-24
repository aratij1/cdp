# CDP Simplification Plan

No removal is performed during the architecture reset.

## Preferred model

`ROUTE -> PAGE OBSERVATION -> FIELD LOCALIZATION -> TOKEN CANDIDATE -> bounded REGIONAL OCR if insufficient -> NORMALIZATION -> EVIDENCE BUNDLE -> FIELD DECISION -> CLAIM DECISION`.

CMS and UB share this skeleton. CMS owns a field graph; UB owns a structural map and service-line reconstruction. Tier D owns family routing and generic layout candidate generation. All three converge at validation for final field decisions and at `ClaimDecisionService` for STP.

## Removal/deprecation sequence

1. Before the next experiment, run evaluation with runtime route/evidence-policy identities and fail the run when the recorded identities differ. This is a measurement precondition, not an optimization treatment.
2. Execute only the one regional RapidOCR crop-preparation experiment described in the failure decomposition.
3. After that experiment is decided, move the generic Tier D `EvidenceDecisionService` call out of extraction and into validation; retain the same service and policy.
4. Mark direct `extract_fields` and regional-table OCR as registered-geometry compatibility APIs, not alternate canonical paths.
5. Move historical phase evaluators that instantiate services directly into a read-only archive namespace with immutable manifests.
6. Remove stale report generators that can overwrite a later summary without binding code/config/data hashes.

## Explicit non-goals

No OCR engine, threshold, crop bounds, evidence/HITL/STP policy, routing rule, normalization, model, cloud path, concurrency, or calibration change is authorized by this plan. The reset selects exactly one next implementation unit: use the existing field-profile preparation in the existing single regional RapidOCR call.
