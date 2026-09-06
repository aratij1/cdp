Current production-closure work is tracked in [PRODUCTION_CLOSURE.md](PRODUCTION_CLOSURE.md). The report below is the historical iteration-six result; its status used the earlier enablement criteria.

---

# CDP final closure status ? iteration 6

Status: **PRODUCTION_ENABLEMENT_PATH_PROVEN**. Engineering extraction is technically closed on the frozen cohort; production qualification remains pending. **PRODUCTION_READY is false.** The five-second latency target is not met, authoritative providers are unconfigured, and independently reviewed release truth is unavailable.

## Technical extraction

| Metric, same 200 fields / 20 claims | Iteration 5 | Iteration 6 | Meaning |
|---|---:|---:|---|
| Technical blocker codes | 15 | 0 | No residual CDP-controlled blocker in this audited cohort |
| Technical review fields | 7 | 0 | Source review remains external |
| Technical field HITL | 3.5% | 0% | Engineering target <=10% met |
| Technically clean claims | 17/20 | 20/20 | Zero technical blockers; not production acceptance |
| Technical STP capability | 85% | 100% | Engineering target >=80% met |
| Evidence-required field HITL | 77% | 77.5% | Source ownership corrected |
| Total observed field HITL | 77.5% | 77.5% | No total HITL improvement |
| Governed candidate Recall@5 | 94.5% | 94.5% | Frozen engineering references; 98% target remains unmet |
| C3 candidate Recall@5 | 100% / 30 fields | 100% / 30 fields | Preserved |

The remaining 15 codes were traced across seven fields, including three candidate-generation fields and four association-conflict fields. Full-resolution source inspection found competing printed values or obscured characters within the same cells. All 15 moved to SOURCE_REVIEW_REQUIRED; **zero extraction fixes or accuracy gains are claimed this iteration**. Cumulative source reclassification is 61 blocker codes across 25 fields in six claims. Existing source-review assignments remain in place.

Each inspection is bound to source-image and crop-pixel hashes. No candidate is selected by the inspection, no character is invented and no OCR retry was used to resolve source ambiguity. Detailed traces and inspections remain local. No residual software blocker is identified in this fixed cohort; this is not a universal technical ceiling for unseen documents.

Extraction state is separate from authority state, including NPI where business authority is required. The conservative original candidate-state audit records 89 ambiguous and one failed identity-like extraction state across 90 fields. Zero technical blockers does **not** mean every field is confidently extracted: source limitations and incomplete source evidence still require review. Missing authority cannot downgrade a genuinely confident extraction, and existing authoritative conflicts cannot be overridden.

The source-bound 200-field replay reproduced the baseline cohort, evidence and canonical-output hashes. Perception, routing, registration, candidate generation, validation thresholds and production acceptance behavior are unchanged. The technical freeze manifest binds the implementation commit, component/configuration/benchmark hashes, model version and validation results.

## Claim-level evidence and minimum enablement

| Requirement | Unique claims |
|---|---:|
| Member / eligibility authority | 20 |
| Provider authority | 20 |
| Patient identity authority | 20 |
| Insured identity authority | 10 |
| Source-evidence verification | 20 |
| Source review | 6 |
| Business-policy exception, recorded | 0 |
| Source conflict / overprint | 6 |

Counts overlap and must not be added. Patient and insured identity share a capability only when a provider supplies separately scoped records for both roles. Source conflict is the reason for source review, not an additional duplicated capability.

The claim combinations are:

- INSURED_IDENTITY_AUTHORITY + MEMBER_AUTHORITY + PATIENT_IDENTITY_AUTHORITY + PROVIDER_AUTHORITY + SOURCE_EVIDENCE: 7 claims.
- INSURED_IDENTITY_AUTHORITY + MEMBER_AUTHORITY + PATIENT_IDENTITY_AUTHORITY + PROVIDER_AUTHORITY + SOURCE_EVIDENCE + SOURCE_REVIEW: 3 claims.
- MEMBER_AUTHORITY + PATIENT_IDENTITY_AUTHORITY + PROVIDER_AUTHORITY + SOURCE_EVIDENCE: 7 claims.
- MEMBER_AUTHORITY + PATIENT_IDENTITY_AUTHORITY + PROVIDER_AUTHORITY + SOURCE_EVIDENCE + SOURCE_REVIEW: 3 claims.

Exhaustive subset enumeration gives the minimum capability combination:

**MEMBER + PROVIDER + IDENTITY + SOURCE EVIDENCE + SOURCE REVIEW.**

The first four capabilities would leave six source-review claims and make **14/20 (70%)** potentially eligible. Resolving source review for **two of those six** would reach **16/20 (80%)**, with a conditional 20% claim-HITL floor. Resolving all six would yield the 20/20 scenario ceiling. This counts capabilities, not necessarily separate vendor integrations.

| Scenario | Technically capable | Evidence-capable | Potential STP | Potential claim HITL |
|---|---:|---:|---:|---:|
| S0_CURRENT | 20/20 | 0/20 | 0% | 100% |
| S1_MEMBER | 20/20 | 0/20 | 0% | 100% |
| S2_PROVIDER | 20/20 | 0/20 | 0% | 100% |
| S3_MEMBER_PROVIDER | 20/20 | 0/20 | 0% | 100% |
| S4_IDENTITY | 20/20 | 0/20 | 0% | 100% |
| S5_SOURCE_EVIDENCE | 20/20 | 0/20 | 0% | 100% |
| S6_SOURCE_REVIEW_RESOLVED | 20/20 | 0/20 | 0% | 100% |
| S7_ALL_EXTERNAL | 20/20 | 20/20 | 100% | 0% |

Every scenario assumes all listed requirements are genuinely satisfied and independent release qualification subsequently passes. These are ceilings under the cohort's recorded requirements, not measured production STP or a new universal payer policy.

## Evidence policy and adapters

Implemented read-only member/eligibility, provider-master, patient/subscriber identity and source-evidence adapters, reusing existing snapshot types. Unconfigured providers return NOT_AVAILABLE. Snapshot adapters enforce exact context, payer/person/provider role, service-date validity, uniqueness, required comparison fields, integrity pinning and mutation detection. Results retain source/version/record provenance and retrieval timestamp. No provider data was fabricated. No automatic ACCEPT, production authority or release truth is created.

The source adapter verified that **all 20 existing source images are AVAILABLE** with their fixture and OCR-region provenance. This does not supply independent verification or resolve conflicting print; it cleared **zero** review requirements. SOURCE_EVIDENCE_REQUIRED must not be interpreted as a missing file. The live source adapter remains unconfigured; the available-source probe is scoped to existing frozen fixtures.

The policy audit examined the governed field-evidence registry, deterministic field-policy helper and risk policy. Thirty fields satisfy existing narrow deterministic policies; 20 are already canonically accepted. Ten tax fields satisfy the syntax/section helper but lack complete candidate provenance. The full evidence guard remains in place, so no policy exemption was retained. No mandatory business control was removed.

Adapter contracts and owner requirements: [iteration6_adapter_contracts.md](closure/iteration6_adapter_contracts.md).

## Latency qualification

The final test used one long-lived RapidOCR model bundle, eight ONNX threads, CPU arena, default recognition batch, one worker, fresh inference and the same 12 pages in fixed order. Constituent model sessions were reused; no per-page model construction occurred. All semantic hashes matched across the initial pass and three warm repetitions.

| Metric | Measured |
|---|---:|
| Cold model initialization | 1.270s |
| Cold-start P95 | NOT_EVALUABLE: one process start |
| First-pass page P95, initialization separate | 9.023s |
| Warm run 1 P95 | 8.319s |
| Warm run 2 P95 | 13.872s |
| Warm run 3 P95 | 15.644s |
| Median warm P95 | **13.872s** |
| Median warm P50 / P99 | 5.553s / 13.872s |
| Median throughput | 0.166 pages/s |
| OS peak working set | 1.620 GB |
| Maximum sampled RSS | 1.443 GB |
| Minimum sampled available system memory, warm | 5.683 GB |
| Total measured warm GC pauses | 12.39ms |

OCR inference accounts for 87.2% of page time, with mean 5.191s; identity accounts for 11.2%. I/O, decoding, preprocessing, postprocessing, candidate generation, effective state, consistency, evidence and serialization are measured separately. Process CPU time, context-switch counters, memory, page dimensions, order, cache state and GC observations are retained locally. Historical scheduling telemetry is unavailable; the exact cause of run-to-run host variability remains unisolated.

**SAFE_LATENCY_CEILING: retained configuration target not met; absolute ceiling not proven.** Inference dominates, so the measured overhead reductions available outside OCR would not establish a stable five-second result. No speculative OCR configuration or rejected optimization was reopened.

This harness includes fresh perception and downstream shadow processing. It exercises six discovered standard-form field pairs per repetition; complete claim context and live business providers are unavailable. It is not a full production SLA measurement. An initial diagnostic run omitted standard-form candidates from downstream timing; the harness was corrected and all four passes repeated. Total fresh OCR calls this iteration: 96 (48 diagnostic, 48 final qualification). No model/candidate semantic tuning was performed.

## Same 100-page operational replay

| Metric | Result |
|---|---:|
| Candidate-bearing pages | 48/100 |
| Alternatives | 87 |
| Candidate-bearing / ambiguous field pairs | 78 / 7 |
| No-candidate pages | 52 |
| Effective-state assessed field pairs | 78 |
| Effective extraction state | 78 EXTRACTED_AMBIGUOUS |
| Routing cohort | 100 OTHER_CLAIM_FORM |
| New full-page / regional OCR calls | 0 / 0 |
| LLM calls | 0 |
| OTHER / UNKNOWN canonical localization | 0 / 0 |
| Cached candidate-generation P95 | 12.174ms |
| Whole cached replay elapsed | 2.449s |
| Observed RSS | 0.087 GB |

Candidate counts, cohort and source evidence are unchanged. Effective-state coverage is measured only for discovered field pairs, not all fields that a complete claim should contain. This replay is cached and is not an accuracy or end-to-end latency measurement. The UNKNOWN safety rule is also covered by regression tests. False-UB04 canaries pass separately, 3/3. The 150-page blind-review manifest remains unchanged and contains no predictions or generated labels.

## Safety and validation

Full suite: **1,542 passed, six skipped**, versus 1,516 passed/six skipped previously. The same two dependency warnings remain. Focused suite: **85 passed**. New semantic failures: **0**. Critical safety regressions, canonical changes and newly accepted shared-provenance evidence: **0**. Three false-UB04 canaries: **3/3 PASS**.

Ruff on changed files, scoped mypy (`--follow-imports=skip`, seven files), architecture validation, Compose configuration and diff checks pass. Repository-wide typing is not claimed clean; iteration five recorded 98 import-following errors in unchanged baseline files.

## Production scorecard

| Target | Status |
|---|---|
| Accuracy >=98% | NOT_EVALUABLE |
| Critical accuracy >=99.5% | NOT_EVALUABLE |
| Accepted precision >=99.5% | NOT_EVALUABLE |
| Critical false accepts =0 | NOT_EVALUABLE on production truth; engineering safety preserved |
| Field HITL <=10% | NOT_EVALUABLE |
| Claim HITL <=20% | NOT_EVALUABLE |
| STP >=80% | NOT_EVALUABLE |
| P95 <=5s/page | NOT_QUALIFIED; warm shadow benchmark exceeds target |
| Paid AI <=$0.001/page | $0 observed paid AI; infrastructure cost unknown |

## Ownership and next action

- **CDP:** preserve the frozen extraction behavior, source-ownership assessments and fail-closed adapters. Residual software blockers on this cohort: zero; universal software ceiling unproven.
- **Member/provider/identity owners:** supply real, governed reference snapshots or service implementations with the required scoped records. No business authority integration is currently active.
- **Source-evidence owner:** satisfy the recorded verification gaps; existing bytes alone are insufficient.
- **Source-review owner:** independently resolve at least two of six source-review claims after the core capabilities are satisfied to reach the cohort's conditional 80% threshold. All six require resolution for the 100% scenario.
- **Trusted-evaluation owner:** complete the existing 150-page independent review/adjudication handoff, freeze truth and split by package before actual release scoring. Keep the final holdout separate from tuning.
- **Latency owner:** qualify the same frozen model/configuration on a controlled deployment worker and resolve the measured inference/host scheduling bottleneck. A production-like path with real business integrations still needs SLA qualification.

The immediate step toward actual production qualification is to return the independently reviewed blind cohort and configure the governed evidence inputs. Reopening broad OCR tuning is not the next action. Production release remains blocked until trusted scoring, evidence requirements and the latency target all pass.

Detailed claim/source audits, semantic hashes and benchmark traces remain under ignored `evaluation_results/closure_iteration6/`. Only code, synthetic tests and PHI-safe aggregate documentation are committed.
