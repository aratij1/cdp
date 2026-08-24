# CDP Duplicate and Competing Path Audit

| Area | Implementation | Classification | Action |
| --- | --- | --- | --- |
| Standard forms | `StandardFormProcessingService.process` + `extract_fields_from_observation` | `CANONICAL_RUNTIME`, `CANONICAL_EVALUATION`, `SHARED` | Keep as the preferred CMS/UB path |
| Standard forms | `extract_fields_from_resolved_rois` -> `extract_fields` | `LEGACY`, active fallback | Keep only behind accepted registered geometry; label compatibility fallback |
| Standard forms | historical engineering/holdout evaluators constructing `StandardFormExtractionService` directly | `EXPERIMENT_ONLY`, `LEGACY` | Archive after extracting immutable result manifests |
| UB tables | `UB04ObservationServiceLineExtractor` | `CANONICAL_RUNTIME`, `CANONICAL_EVALUATION`, `SHARED` | Keep; observation-token geometry is primary |
| UB tables | `UB04ServiceLineExtractor` with regional table OCR/grid detection | `LEGACY`, active fallback | Keep only for registered/fallback path |
| UB tables | `UB04ServiceLineEngine` | `SHARED` | Keep as the one row/column reconstruction owner |
| Field validation | `decide_local_candidate` in extraction | `SHARED` candidate parser/validator | Keep, but never describe its `accepted` flag as final acceptance |
| Field decisions | `EvidenceDecisionService` in validation/retry | `CANONICAL_RUNTIME`, `SHARED` authority | Keep |
| Field decisions | `EvidenceDecisionService` inside unstructured extraction | `DUPLICATE`, `SHADOW` decision site | Remove the call site; pass candidates to validation |
| Claim decisions | `ClaimDecisionService` in validation | `CANONICAL_RUNTIME`, `SHARED` authority | Keep |
| Evidence policy | runtime default policy/route mode | `CANONICAL_RUNTIME` | Keep |
| Evidence policy | balanced policy + evaluation route mode in Phase 8.10 replay | `CANONICAL_EVALUATION`, competing config | Retain for historical replay, but never claim runtime parity |
| Unstructured | known-family anchor crops | `CANONICAL_RUNTIME` Tier D fast path | Keep |
| Unstructured | generic `BundleDLayoutEngine` | `SHARED`, explicit fallback | Keep when known-family extraction produces no candidates |
| Unstructured | TrOCR/VLM escalators | `EXPERIMENT_ONLY`, optional gated fallback | Keep candidate-only, crop-only, and policy-gated |
| Routing | page-detection processing route | `CANONICAL_RUNTIME` routing authority | Keep |
| Routing | evaluator-supplied verified identity | `CANONICAL_EVALUATION` authority | Keep only with explicit benchmark label; it does not measure classification |

The repository contains many old phase evaluators. They are not runtime implementations, but their direct service construction makes accidental reuse easy. They should be moved to an archive namespace or guarded by a historical-manifest marker after the reset experiment, not deleted during this audit.
