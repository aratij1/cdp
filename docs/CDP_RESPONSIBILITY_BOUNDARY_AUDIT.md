# CDP Responsibility Boundary Audit

| Boundary | Current owner | Violation or ambiguity | Severity | Required target |
| --- | --- | --- | --- | --- |
| Route selection | Page detection/document routing | Evaluation injects verified family, so classification is unmeasured | Medium | Label classification out of scope; add separate routing benchmark |
| Field localization | CMS graph / UB locator + `DynamicROIResolver` | Registered fallback and dynamic path coexist but are explicitly gated | Low | Preserve dynamic primary, registered fallback only |
| OCR | Page observation + standard extraction | Candidate parsing exposes an `accepted` boolean that can be confused with final acceptance | Medium | Rename/document as datatype-valid candidate only in a later change |
| UB reconstruction | `UB04ServiceLineEngine` | Two feeders exist: observation tokens and regional table OCR | Low | Keep one shared engine and explicit feeder provenance |
| Evidence construction | Evidence builder and evidence services | No observed authority duplication; unknown lineage fails closed | Low | Freeze |
| Field decision | `EvidenceDecisionService` | Called both in validation and generic unstructured extraction | High | One decision site in validation |
| Claim decision | `ClaimDecisionService` | No competing runtime owner found | Low | Freeze |
| HITL task creation | Validation/retry | Extraction emits suggestions only on standard path; unstructured persists early dispositions | Medium | Candidate-only extraction, validation-only review authority |
| Evaluation | Phase 8.10 evaluator | Evaluation policy and route differ from runtime while parity is reported PASS | Critical | Fail parity unless all config identities match |
| Cost | Phase evaluator | Local stage CPU not metered; review cost is modeled | Medium | Report modeled vs measured separately |

## Boundary verdict

The extraction architecture is substantially converged, but decision placement and evaluation configuration are not. The most consequential violation is not a field algorithm: it is the evaluation plane's ability to declare parity without comparing policy and route identities. This reset does not repair it because the requested output is diagnosis plus one future implementation unit, not another implementation phase.
