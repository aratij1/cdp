# CDP Phase 8.2 Runtime Extraction Parity

Baseline Git SHA: `9e6d0558f346f157c8e9f92fcbdcccb7f4cec662`
Dirty state at start: six inaccessible pre-existing `test-artifacts` deletions and one generated pytest temp directory; neither was modified as product work.

## Result

Runtime and evaluation now call `StandardFormProcessingService`. Production supplies an upstream verified `FormIdentityDecision`; evaluation supplies a truth-route identity solely to isolate extraction. The canonical service contains no truth lookup, family inference from benchmark metadata, or forced score.

| Component | Golden path | Runtime path | Same implementation? | Same config/version? | Gap | Action |
|---|---|---|---|---|---|---|
| Page observation | Canonical service | Canonical service | Yes | Yes: `document-preparation-v1` | None | Shared boundary |
| Full-page OCR | `RapidOCRFullPageTextExtractor` | Same, instrumented/cache wrapper | Yes | Same model/version | Runtime adds audit/cache wrapper | Preserve wrapper |
| CMS field graph | `CMS1500FieldGraph` | Canonical service | Yes | `cms1500-field-graph-v1` | None | Shared boundary |
| UB structure | `UB04StructuralMapDetector` | Canonical service | Yes | Same code | None | Shared boundary |
| Dynamic ROI | `DynamicROIResolver` | Canonical service | Yes | Same code | None | Shared boundary |
| Localization config | `config/field_definitions` | Same | Yes | Same files | None | Shared boundary |
| Regional OCR selection | `StandardFormExtractionService` | Same instance owned by worker | Yes | Same RapidOCR model | Runtime instrumented | Preserve wrapper |
| Reading order | Shared line clustering | Shared line clustering | Yes | Median-height tolerance | Previously duplicated | Centralized |
| Normalization/validation | Extraction service candidate validation | Same | Yes | Same config | Final disposition occurs later | Correct separation |
| UB rows | `UB04ObservationServiceLineExtractor` | Canonical service | Yes | Same engine | Previously separately instantiated | Shared instance |
| Candidate materialization | `StandardFormExtractionService` | Same | Yes | Same template | None | Shared boundary |
| Field disposition | Not benchmark authority | Validation worker | Yes | `EvidenceDecisionService` | Phase 8.1 measured local acceptance proxy | Phase 8.2 feeds canonical decisions |
| Claim STP/HITL | Not benchmark authority | Validation/output path | Yes | `ClaimDecisionService` | Phase 8.1 did not measure | Phase 8.2 measures |

## Authority audit

- `EvidenceDecisionService` remains the sole machine field-disposition authority in runtime validation/retry/unstructured paths.
- `ClaimDecisionService` remains the sole claim STP/HITL authority.
- `packages/hitl_optimization.py` has no production worker callers. It is explicitly classified as legacy evaluation analytics. `CanonicalHITLAuthority` only projects canonical `FieldDecision` objects and cannot re-evaluate or override them.
