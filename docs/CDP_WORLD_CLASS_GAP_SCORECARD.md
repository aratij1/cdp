# CDP World-Class Gap Scorecard

Scores use 0 = absent, 3 = workable but material gaps, and 5 = production-leading with independent validation.

| Dimension | Score | Evidence |
| --- | ---: | --- |
| Document intake | 3.5/5 | Durable object storage, repositories, events, and outbox; production volume evidence is limited |
| Classification | 3.0/5 | Explicit taxonomy, route, and form verification; bypassed by the golden replay |
| Standard extraction | 3.0/5 | Shared canonical processor and provenance; CMS/UB field accuracy remains below 90% |
| Table extraction | 2.5/5 | UB row recall 100%, exact rows 68.54%, cells 85.02% |
| Unstructured extraction | 2.5/5 | Known-family and generic paths are executable; second decision site violates the boundary |
| Field provenance | 4.0/5 | Page/crop/localization/preprocessing/engine lineage is explicit and unknowns fail closed |
| Confidence/evidence | 3.5/5 | Dependency-aware policies are mature; independent evidence availability is low |
| Reference validation | 2.5/5 | Authorized adapter and fail-closed states exist; no production source is active in this replay |
| Business rules | 3.5/5 | Deterministic and claim evidence are versioned; some reporting conflates absence with ambiguity |
| HITL | 1.5/5 | 91.33% field HITL; 87.96% of reviewed fields are correct |
| STP | 1.0/5 | 0% claim STP and 100% claim HITL |
| Cost | 2.5/5 | $0 cloud common path; modeled fully loaded cost is $0.3876/page, mostly review |
| Latency | 2.5/5 | Source A P95 is 10.127 s and Source C P99 is 15.150 s |
| Scale | 2.5/5 | Event workers and caches support scaling; the reset has no production-scale proof |
| Resilience | 3.0/5 | Outbox, retries, fail-closed routing, and caches exist; end-to-end failure testing is incomplete |
| Security | 3.5/5 | Crop-only gated external paths and explicit authorization exist; no independent security audit is in scope |
| Observability | 2.5/5 | Rich artifacts and OCR audit lineage; stage CPU/latency attribution is incomplete |
| Evaluation/generalization | 2.0/5 | Three source-disjoint synthetic sources exist; policy parity is false and external execution is blocked |

Plane roll-up: Document 3.5/5, Extraction 3.0/5, Evidence 3.5/5, Decision 3.5/5, Evaluation 2.0/5.

The primary world-class gap is measurement authority. The platform cannot safely optimize what it cannot compare under identical runtime configuration.
