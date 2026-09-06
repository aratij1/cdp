# CDP closure iteration 2

Status: CONTINUE. Production authority remains disabled.

## Measurement correction

All 31 previously reported ranking misses were name-format mismatches under the existing governed name-agreement policy. They were not wrong selections. Two of the original 37 missing cases are also representation mismatches. The original exact-string benchmark is preserved below; corrected comparison scores are not claimed as extraction gains.

## Fixed 200-field engineering benchmark

| Metric | Baseline | Current | Target | Status |
|---|---:|---:|---:|---|
| Exact-string Recall@5 | 81.5% | 85.5% | 98% | OFF_TARGET |
| Governed-name comparison Recall@1 | 82.5% | 83.5% | 97% | OFF_TARGET |
| Governed-name comparison Recall@3 / @5 | 82.5% | 90.0% | 98% | OFF_TARGET |
| Exact-string missing candidates | 37 | 29 | 0 | OFF_TARGET |
| Governed-comparison missing candidates | 35 | 20 | 0 | OFF_TARGET |
| Genuine selected-value ranking misses | 0 | 14 | 0 | OFF_TARGET |
| C3 Recall@5 (30 fields) | 96.67% | 100% | 99% | ENGINEERING_ONLY |
| Technical blockers | 106 | 71 | 0 | OFF_TARGET |
| Technical review fields | 64 | 29 | 0 | OFF_TARGET |
| Claims with zero recorded technical blockers | 0 | 14 | >0 | ENGINEERING_ONLY |

The new ranking misses are recovered alternatives that are not yet safely selected. Candidate Recall@1 and selected-value correctness are distinct when selection abstains. Eight additional exact candidates were recovered; no reference string enters extraction. Thirty-five ambiguity blockers were duplicate name representations. Removing them does not add independent evidence or remove authority requirements.

Historical 130-field comparison: {"CDP_CONTROLLED_HITL_after": 24, "CDP_CONTROLLED_HITL_before": 59, "distance_1_to_0": 1, "distance_2_to_0": 8, "evidence_hitl_after": 122, "evidence_hitl_before": 122, "technical_blockers_after": 59, "technical_blockers_before": 94}.

Fourteen full-frozen-cohort claims now have zero recorded technical blockers; remaining distances are 1, 3, 14, 16, 17 and 20. Frozen declared form identity is not real strict-identity authorization. These are diagnostic engineering unlocks, not complete real-claim STP. Production accuracy, precision, false accepts, HITL and STP remain null / NOT_EVALUABLE.

## Root causes and retained changes

Every original missing case has exactly one primary diagnosis: {"OCR_CHARACTER_CORRUPTION": 4, "REFERENCE_MISMATCH": 2, "SPATIAL_WINDOW_MISS": 11, "TOKEN_MERGE_ERROR": 9, "UNKNOWN": 11}. UNKNOWN cases are not declared external or unreadable.

- Bounded left-offset and overlapping-box recovery: seven exact candidates added.
- Field-specific numeric flag exclusion: one additional exact candidate added without character replacement.
- Existing governed name comparison reused in shadow ambiguity checks; observed strings, source dependencies and canonical output remain unchanged.
- Unique, structurally valid source recovery may rank first only when existing extraction is absent or comes from a wrong/missing crop; decisions emit field-family reason codes and remain shadow-only.

## Real operational replay

Same 100 pages, same source/evidence hashes, every blind-review package excluded. Candidate-bearing pages 38 to 46; alternatives 66 to 84. Current 75 field pairs, seven ambiguous field pairs, 54 pages with no candidate. All candidates remain UNVERIFIED_DISCOVERY. OTHER/UNKNOWN canonical localization remains zero. The 150-page blind review selection is unchanged.

Cached source validation and discovery took approximately 1.9 seconds for the cohort; this excludes OCR and complete claim processing. Candidate generation P95 was approximately 10 ms/page; observed process RSS approximately 88 MB. Zero new full-page/regional OCR calls and zero VLM calls in this replay. These are coverage and operational measurements, not accuracy.

## Fresh latency and rejected experiments

Three separate-process repetitions used identical 12-page cohorts, eight threads, CPU arena enabled and one worker. Exact token evidence, confidence, candidates and identity outputs matched across all runs.

| Run | P50 ms | P95 / P99 ms | Pages/s |
|---|---:|---:|---:|
| 1 | 4357.47 | 6699.24 | 0.2297 |
| 2 | 4908.35 | 6040.77 | 0.2350 |
| 3 | 5025.39 | 6473.69 | 0.2229 |

Median P95 is 6473.69 ms: the 5000 ms target is not achieved. This is fresh perception, not complete end-to-end claims processing. Cold startup, observed memory and host CPU measurements are recorded separately in the machine-readable report. The earlier variance's precise cause has not been isolated; these repetitions only establish a narrower observed range under controlled OCR concurrency.

Four threads with the arena enabled measured P95 7041.30 ms and were rejected. Wider name regions and expanded diagnosis discovery added no recovery and were reverted. Fifty-six regional OCR calls (~51.5s OCR time) and six fresh full-page calls (~13.0s OCR time) added no incremental recall; broad escalation was rejected. Unconditional source preference was also rejected. See REJECTED_APPROACHES.md.

Paid AI calls/cost: zero for all experiments. Infrastructure and complete processing cost are unmeasured.

## Validation and remaining work

Full suite: {"NEW_SEMANTIC_REGRESSIONS": 0, "architecture": "PASS", "compose": "PASS", "diff_check": "PASS", "duration_seconds": 60.632, "errors": 0, "failures": 0, "false_ub04_canaries": "3/3 PASS", "passed": 1473, "ruff": "PASS", "scoped_mypy": "PASS 8 files", "skipped": 6}.

Remaining work includes genuine source-token merge/corruption cases, the recovered-but-unselected alternatives, and sub-five-second end-to-end latency. Technical ceilings are unproven. No PROJECT_CLOSED or TARGET_MET claim is justified. Local commits are preserved on closure/cdp-target; GitHub publication previously returned 403 for ashishdat on ashneevai/CDP.
