# CDP final production closure ? iteration 7

Status: **TECHNICAL_CLOSED_PRODUCTION_ENABLEMENT_IN_PROGRESS**.
Performance decision: **SAFE_CPU_CEILING_ABOVE_TARGET**.

The local implementation and engineering qualification are complete. The requested `PRODUCTION_ENABLEMENT_PATH_PROVEN` status is not yet justified: no tested replacement runtime preserved all protected fingerprints, and no specific deployment host has been demonstrated to meet five seconds. Production candidate/ready status is also unavailable without independent truth. This report does not claim that a faster host is already qualified.

## Technical extraction

| Measure | Result | Authority |
|---|---:|---|
| Frozen fields / claims | 200 / 20 | Frozen engineering regression |
| CDP-controlled technical blockers | 0 | Corrected blocker ownership |
| Technical field HITL | 0% | Engineering ownership only |
| Technically unblocked claims | 20/20 | Capability, not production STP |
| Total observed field review | 77.5% | Unchanged frozen observation |
| Critical C3 Candidate Recall@5 | 100%, 30 fields | Frozen regression |
| Governed Candidate Recall@5 | 94.5% | Frozen regression |
| Canonical production changes | 0 | Replay comparison |

Source-review ownership remains intact. Zero technical blockers does not establish confident identity extraction or production accuracy. The [architecture freeze](closure/CDP_PRODUCTION_CANDIDATE_FREEZE.json) binds the retained code, models, configuration, benchmark evidence and validation.

## Latency and runtime decision

| Measure | Milliseconds |
|---|---:|
| Earlier same-configuration CPU baseline median warm P95 | 8961.91 |
| Final warm repetition 1 P95 | 10640.68 |
| Final warm repetition 2 P95 | 6629.93 |
| Final warm repetition 3 P95 | 6631.61 |
| Final median warm P50 | 4574.31 |
| Final median warm P95 | 6631.61 |
| Final median warm P99 | 6631.61 |
| Mean recognition inference, nested within OCR | 2914.88 |
| Mean detection inference, nested within OCR | 439.51 |
| Mean strict form identity | 605.99 |
| One model/session initialization | 1433.13 |

Median throughput: 0.2191 pages/sec. Peak observed RSS: 1454571520 bytes; process peak working set: 1626914816 bytes. Target <=5 sec: **FAIL**. The same configuration's timing varied across runs; the lower final observation is not attributed to a new optimization.

Retained runtime: RapidOCR 1.4.4, ONNX Runtime 1.29.0, CPUExecutionProvider, eight threads, one worker, CPU arena enabled, 2,000-pixel OCR max side, unchanged models/preprocessing and recognition batch size. One full-page OCR call/page; model sessions reused. No production configuration was automatically activated.

The twelve real TIFF pages have three complete fresh warm repetitions with identical protected fingerprints. This path exercises fresh perception, strict identity and downstream shadow. Complete production registration/localization, claim business context, external authority and request queue latency are not qualified. One cold initialization is not a cold-start P95 distribution. See the [latency contract](closure/latency_contract.json) and [measured profiles](closure/production_latency_results.json).

The Intel Arc GPU was detected. The isolated DirectML 1.24.4 same-model screen executed GPU nodes but changed protected token/candidate fingerprints. Its same-version CPU control also differed from retained 1.29.0, so GPU-only attribution is not justified. One OpenVINO CPU FP32 recognition alternative, with the same model, also changed protected fingerprints. Both were rejected at the first-page semantic gate; neither has qualified warm P95 or recall results. No engine switch was made on speed alone. Isolated dependencies did not modify the main environment.

Strict identity profiling found phrase comparison/SequenceMatcher dominant; repeated conversion alone does not explain the gap. No anchor shortcut or repeated-page cache gain was claimed. See [runtime capabilities](closure/runtime_capabilities.json), [runtime decision](closure/runtime_decision.json), [identity profile](closure/form_identity_profile.json) and [rejected approaches](REJECTED_APPROACHES.md).

## Evidence and minimum path to 80% STP

Member, provider, patient/subscriber/insured identity and source verification remain NOT_AVAILABLE without actual governed sources. The reference-only configuration contract accepts registry reference names, version, credential-reference name, deadline and TTL; it contains no endpoint or credential and does not activate a provider.

Configured local source bindings distinguish FILE_PRESENT, VERIFICATION_AVAILABLE, VALUE_VERIFIED, CONFLICT, UNREADABLE and NOT_AVAILABLE through the evidence-state projection. All twenty frozen source fixtures are present and unverified. File presence never verifies a field or resolves source review. The Python AVAILABLE alias is retained; serialized file-presence status is explicitly AVAILABLE_UNVERIFIED.

Source reviews require a pinned, scoped record and governed reviewer/policy provenance. NOT_REVIEWED, CONFIRMED_VALUE, CONFIRMED_UNREADABLE and CONFIRMED_CONFLICT remain distinct. No OCR or LLM vote clears a conflict. Existing acceptance and critical-review policies still apply.

The [dynamic minimum path](closure/minimum_stp_path.json) derives capabilities from the actual claim matrix:

| Conditional capability scenario | Potential claims | Potential STP | Potential claim HITL |
|---|---:|---:|---:|
| Member + provider + identity + source verification | 14/20 | 70% | 30% |
| Core capabilities plus confirmed values for all required review fields in two eligible claims | 16/20 | 80% | 20% |
| Same selected reviews remain unreadable, conflicted or not reviewed | 14/20 | 70% | 30% |

Six claims require source review; the successful two-claim scenario leaves four. These are conditional scenarios, not achieved metrics. No review conclusion was created. Marginal capability gains and remaining blocker counts are included in the JSON; they depend on capability order because requirements are conjunctive.

Independent lookups now have an explicit concurrency bound of four, individual deadlines, process-private TTL/rate/cost controls and canonical deep snapshots before queuing. Tests cover nested dictionaries/lists, ordering, type distinction, caller mutation, concurrent requests and provider cache isolation. Deterministic event-barrier doubles measured adapter overhead without pretending to measure a production network. See [evidence readiness](closure/production_evidence_readiness.json).

## Release qualification

The blind handoff remains 150 pages, unchanged and prediction-free. Reviewed: 0; critical dual-reviewed: 0; adjudicated: 0. Pre-truth reservation: 103 development pages from 62 packages, 47 holdout pages from 26 packages. Package overlap: 0; all eleven latency-development packages are disjoint from the blind cohort. The reservation is not an attested release holdout.

The implementation is ready to validate source bindings/reviewer lineage and pass reviewed evidence through existing dual-review/adjudication/truth governance. Prediction-freeze machinery requires complete executed predictions, exact page/package/source coverage and a configuration digest; it rejects mutation or missing outputs. The actual final 150-page prediction snapshot and governed source bindings remain pending. Nothing was fabricated to fill them.

Overall accuracy, critical accuracy, accepted precision, critical accepted precision, critical false accepts, production field HITL, claim HITL and STP are all **null / NOT_EVALUABLE**. The [release-readiness scorecard](closure/production_release_readiness.json) preserves every target.

## Same 100-page operational replay

| Measure | Result |
|---|---:|
| Candidate-bearing pages | 48 |
| Alternatives | 87 |
| Candidate ambiguities | 7 |
| Effective field pairs | 78, all EXTRACTED_AMBIGUOUS |
| New OCR calls/page | 0, cached OCR replay |
| Regional OCR / LLM calls | 0 / 0 |
| Candidate-generation P50 / P95 / P99 | 2.78 / 15.46 / 18.70 ms |
| Observed process RSS | 89714688 bytes |
| OTHER / UNKNOWN canonical localization | 0 / 0 |
| False-UB04 canaries | 3/3 PASS |

This is cached candidate generation, not fresh OCR or end-to-end production SLA. No operational accuracy is claimed.

## Cost, safety and validation

Paid OCR: $0; LLM: $0; observed paid AI/page: $0. Azure rates: PRICING_NOT_CONFIGURED. Compute/page and total/page: null, COMPUTE_COST_NOT_CONFIGURED. No hardware/cloud pricing was invented. Paid AI zero does not mean total compute zero.

Retained semantic regressions: 0; canonical changes: 0; tested form-identity regressions: 0; tested shared-provenance/authority fail-open violations: 0. Rejected challengers are not counted as retained improvements. Production authority remains disabled.

Focused: 90 passed. Full: 1632 passed, 6 skipped, zero failures/errors, two existing dependency deprecation warnings. Baseline: 1542 passed, six skipped, zero failures. Ruff: PASS. Scoped mypy: PASS (changed modules, follow-imports skip). Architecture: PASS. Compose config: PASS. Diff check: PASS. Full suite covers candidate/effective state, claim intelligence/decisions, identity, routing/localization, evidence, Azure closed-world and historical regressions. [Validation evidence](closure/production_validation.json).

## Final gap ownership and smallest remaining actions

| Area | Owner and concrete remaining input |
|---|---|
| Extraction | Engineering: frozen regression closed; preserve retained semantics |
| Latency | Deployment/runtime owner: supply one dedicated higher-throughput test host for the exact retained runtime, or approve a separately qualified runtime port; demonstrate <=5 sec with identical fingerprints |
| Member authority | Data owner: governed membership snapshot or documented transport, scope, version and access reference |
| Provider authority | Data owner: governed provider-master source and matching scope |
| Identity authority | Data owner: governed patient/subscriber/insured identity source and role rules |
| Source verification | Evidence owner: verified source/region bindings and governing policy |
| Source review | Independent reviewers: actual conclusions for required fields; at least two eligible claims must be fully resolved for the conditional 80% path |
| Trusted qualification | QA/review owner: independent 150-page reviews, critical dual review/adjudication, truth manifest and untouched-holdout attestation; freeze actual final predictions separately before scoring |
| Pricing | Deployment/finance owner: actual infrastructure and authority pricing; Azure rates only if paid AI is enabled |

The runtime host must improve measured page latency by at least 1.326x before accounting for unmeasured production stages. This is a lower-bound requirement, not a demonstrated host capability. No additional arbitrary CPU thread/worker or resolution sweep is recommended.

Detailed OCR, source-review content, images and runtime caches remain outside Git. Only code/tests and aggregate PHI-safe reports are retained.
