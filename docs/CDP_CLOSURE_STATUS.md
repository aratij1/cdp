# CDP closure iteration 5

Status: **BLOCKER_COLLAPSE_ACHIEVED**. The fixed engineering cohort has 15 technical blockers and 17/20 technically clean claims (85%). Production authority remains disabled. This result does not establish production qualification or a technical ceiling.

## Comparative scoreboard

All semantic measurements below use the same frozen 200 fields / 20 claims. Source inspection is engineering evidence, not independently adjudicated release truth.

| Metric | Previous | Current | Delta | Target / status |
|---|---:|---:|---:|---|
| Technical blockers | 71 | 15 | -56 | <=20: met |
| Technical review fields | 29 | 7 | -22 | Engineering only |
| Technical field HITL | 14.5% | 3.5% | -11 pp | Engineering only |
| Evidence-required field HITL | 77% | 77% | 0 | Requirements retained |
| Total observed field HITL | 77.5% | 77.5% | 0 | No overall HITL gain |
| Technically clean claims | 14/20 | 17/20 | +3 | >=16/20: met; preferred 18/20 unmet |
| Technical STP capability | 70% | 85% | +15 pp | >=80%: met |
| Governed candidate Recall@5 | 94.5% | 94.5% | 0 | 98% unmet |
| C3 candidate Recall@5 | 100% / 30 | 100% / 30 | 0 | Preserved |
| Exact / governed missing candidates | 22 / 11 | 22 / 11 | 0 | Perception frozen |
| Correct selected values, frozen governed comparison | 166 | 168 | +2 | Not production accuracy |
| Fresh perception median P95 | 5.581s | 8.255s | +2.674s | <=5s unmet |
| LLM calls / paid AI cost | 0 / $0 | 0 / $0 | 0 | Infrastructure cost unknown |

## Blocker funnel and retained changes

Every one of the 71 starting blocker codes has a local trace through source, OCR, candidates, selection, normalization, validation, consistency, evidence, authority and acceptance. Source and crop pixel hashes bind 18 direct source inspections: 12 cells contain multiple printed values, five contain overprint, and one has illegible characters. These are engineering pixel inspections, not human truth labels.

**46 blocker codes were reclassified to source review. This is not an extraction or accuracy gain.** Existing external requirements remain. Nine stale acquisition codes across three fields were resolved using unique literal, provenance-bound member-ID or relationship candidates. One member-ID ambiguity code was resolved by the existing structural validator, with confirmed geometry and source agreement. These changes affect the explicit shadow engineering assessment; production acceptance thresholds and canonical decisions are unchanged.

| Stage | Technical codes | Technical fields | Clean claims |
|---|---:|---:|---:|
| Baseline | 71 | 29 | 14 |
| Source ownership correction | 25 | 11 | 16 |
| Bounded document recovery | 16 | 8 | 16 |
| Field validation correction | 15 | 7 | 17 |

Primary root causes: candidate absent 4; wrong rank 0; normalization 0; validation defect 1; claim consistency 0; evidence policy 0; downstream acquisition/acceptance bookkeeping 9; authority reclassified 0; source evidence reclassified 46; real technical association conflicts 11. Ten codes were resolved, 46 moved to external review, and 15 remain technical.

Residual technical HITL spans seven fields: candidate generation 3, technical association conflict 4, ranking 0, normalization 0, validation 0, consistency 0, other software policy 0. Claim distances are zero for 17 claims, two for two claims, and eleven for one claim. Detailed residual traces remain local; no technical ceiling is claimed. The earlier nearest provider and overprinted fields now correctly require source review, with no invented character or canonical value.

## External requirements and conditional scenarios

All 20 claims still require member authority, provider authority, patient/insured identity and source evidence; all 17 technically clean claims also retain those requirements. Field requirement counts are 20 member, 20 provider, 30 identity and 93 source, with overlap. There are 12 source-conflict review fields and zero recorded business-policy review fields.

Providing any single authority source or a partial subset cannot qualify these claims. If **all** external requirements are satisfied **and** independent release qualification passes, 17/20 claims could potentially qualify, implying a conditional 15% claim review floor. This is a scenario, not achieved production STP. Observed production qualification remains unavailable.

The existing 150-page blind review manifest is preserved. No predictions or labels were added and no reviewers were contacted. Production accuracy, critical accuracy, accepted precision, critical false accepts, field/claim HITL and STP remain **null / NOT_EVALUABLE** without trusted truth.

## Final latency qualification

After blocker collapse, three fresh repetitions used the same 12 pages, eight ONNX threads, memory arena, default recognition batch and one worker. P95 was **6.042s, 9.479s and 8.255s**, median **8.255s**. Median P50 was 4.806s; median P99 8.255s; median throughput 0.213 pages/s; maximum sampled RSS 1.39 GB. Cold model loading is reported separately. All five semantic comparisons matched the retained baseline.

The configuration is unchanged and the cause of runtime variation is not isolated. No new runtime configuration was retained or rejected option reopened. The harness covers fresh OCR, routing and spatial shadow extraction, not the complete production claim path; it does not measure the new blocker assessment. The five-second target is not met. Blocker replay used zero new OCR calls; final qualification used 36. LLM calls and paid AI cost were zero; infrastructure cost is unknown.

## Validation and artifacts

Full suite: **1,516 passed, six skipped**, versus 1,497 passed and six skipped previously; the same two dependency warnings remain. **NEW_SEMANTIC_FAILURES = 0**. Focused blocker/pipeline suite: 59 passed. Three false-UB04 canaries pass; OTHER and UNKNOWN canonical localization remain zero. Perception code, frozen inputs, observation evidence and canonical output checks match the baseline. No production authority is enabled.

Ruff, scoped mypy (`--follow-imports=skip`, five changed files), architecture validation, Compose configuration and diff checks pass. Import-following mypy reports 98 errors in 46 files verified unchanged from the baseline; repository-wide typing is not clean. The changed scope is the explicit engineering blocker assessment, its frozen replay, synthetic tests, dashboard and aggregate documentation.

Required aggregate artifacts and the 71 detailed traces are under ignored local `evaluation_results/closure_iteration5/`. Fresh repetitions are under `evaluation_results/closure/iteration5/`. Source inspections, field/claim identifiers, source pixels, OCR text and runtime details stay outside Git. The committed aggregate summary is `docs/closure/iteration5_summary.json`.
