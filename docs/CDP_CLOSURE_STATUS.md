# CDP closure status

PROJECT STATUS: CONTINUE

Production authority remains disabled. No closure gate is qualified.

The local CDP2 commit is preserved on closure/cdp-target. Origin is ashneevai/CDP.

## Current evidence

Frozen regression target subset: 20 claims / 130 fields; 94 technical blockers, 122 evidence blockers; 59 CDP-controlled review fields. These are not release scores.

| Field | Regression R@1 | R@3 | R@5 | Release status |
|---|---:|---:|---:|---|
| insured_name | 10.0% | 70.0% | 70.0% | NOT_EVALUABLE |
| member_id | 85.0% | 85.0% | 85.0% | NOT_EVALUABLE |
| patient_dob | 75.0% | 75.0% | 75.0% | NOT_EVALUABLE |
| patient_name | 5.0% | 70.0% | 70.0% | NOT_EVALUABLE |
| principal_diagnosis | 70.0% | 70.0% | 70.0% | NOT_EVALUABLE |
| provider_name | 10.0% | 70.0% | 70.0% | NOT_EVALUABLE |
| service_date | 80.0% | 80.0% | 80.0% | NOT_EVALUABLE |
| total_charge | 85.0% | 85.0% | 85.0% | NOT_EVALUABLE |

All production accuracy, precision, false-accept and STP values remain null.

## Retained engineering changes

- Inverse preprocessing geometry: recover known source boxes through borders, scaling and rotation.
- Printed field-number labels: recover 24/24 controlled field cases; add structurally valid real candidates; their correctness remains unverified.
- Candidate duplicates retain provenance; at most five alternatives leave the spatial extractor.

## Remaining work

Fresh OCR recognition dominates latency. Eight threads won the broader 12-page experiment. Perception timing is not complete claim-processing latency.

The 2,173-page corpus currently has two verified CMS1500 pages and no verified UB04 pages. Identity gates are preserved. The remaining candidate and runtime gaps are not proven external; no technical ceiling or PROJECT_CLOSED claim is justified.

Independent review, source binding and member/provider authority remain external dependencies. The separate blind 150-page review manifest remains available under evaluation_results/cdp2.

Machine-readable dashboard and residual field records: evaluation_results/closure/ (untracked runtime artifacts).

## Closure iteration results

- Iteration 1: Correct preprocessing-to-source token geometry. Known source boxes recovered exactly through borders, scaling and rotation
- Iteration 2: Printed label formatting, neighboring-cell ownership and numeric assembly. Targeted known-source recovery 0/24 to 24/24; original 17 invalid real-date alternatives removed; 10 structurally valid real alternatives now available across six page-field pairs
- Iteration 3: Bounded RapidOCR thread profiling. Eight threads on this 16-CPU host: P95 16.18s vs 21.32s at four threads; exact semantics on 12 identical pages; runtime profile only, production defaults unchanged
- Iteration 4: Bind OCR cache to precise region, source and preprocessing configuration. Reproduced false cross-region cache hit now prevented; unchanged requests still reuse exact evidence
- Iteration 5: Preserve frozen byte hashes across Windows checkouts. Four CRLF-induced historical test failures resolved by restoring exact committed LF bytes; hash assertions unchanged
- Iteration 6: Literal-label noncanonical discovery with inline values and checksum-valid NPI candidates. 66 unverified alternatives across 38 of 100 OTHER pages; 24/24 controlled source cases; zero canonical localization; all blind-review packages excluded
- Iteration 7: Explicit default-off CPU memory arena profile. Paired 12-page P95 16.38s to 5.83s with exact token evidence and decisions; peak RSS 1.40GB. Repeat same configuration P95 8.99s: no reliable 8s or 5s target achievement
- Iteration 8: Respect provider PERSON_OR_ORGANIZATION datatype while retaining identity authority requirements. Technical blockers 110 to 94 on identical 130-field cohort; all 20 canonical claim hashes unchanged; CDP-controlled review 59, evidence review 122 and engineering unlocks zero remain unchanged
- Iteration 9: Exclude padding-only OCR output from field candidates and invalidate provider cache version. Reproduced padding-only output now yields no candidate; mapped source text retained
- Iteration 10: Execute independent all-field candidate decomposition. 200 frozen fields: R@1 66%, R@3/R@5 81.5%; 37 missing reference candidates, 31 ranking misses; 40 fields have no shadow structural validator. Original 130-field comparison unchanged

Validation: {"NEW_SEMANTIC_REGRESSIONS": 0, "OTHER_UNKNOWN_canonical_localization": 0, "architecture": "PASS", "baseline_environment_issue": "Four historical failures caused only by CRLF checkout bytes, repaired without changing frozen content", "compose": "PASS", "diff_check": "PASS", "failures": 0, "false_ub04_canaries": "3/3 PASS", "full_suite_passed": 1461, "full_suite_skipped": 6, "intermediate_failure": "One new discovery test omitted required package binding; fixed fixture, retained guard; final full suite passed", "mypy": "PASS 11 files; repository-style --follow-imports=skip --ignore-missing-imports", "ruff": "PASS", "unrestricted_mypy": "FAIL: 96 errors in 46 files, including transitive imports and missing third-party stubs; not claimed clean"}


## Fresh perception runtime

Includes decode, preprocessing, fresh OCR, strict routing and spatial extraction. Excludes complete claim processing and model cold start; those targets remain unqualified.

| Threads | Pages | P50 ms | P95 ms | P99 ms | Pages/sec |
|---|---:|---:|---:|---:|---:|
| 8 | 12 | 11395.94 | 16175.51 | 16175.51 | 0.0956 |
| 4 | 12 | 15270.85 | 21316.53 | 21316.53 | 0.0735 |

## Exact remaining gaps

- Regression Recall@5 is 76.15%, below the candidate-recall target; no real release recall is available.
- Technical blockers decreased 110 to 94; review fields remain 59 and engineering claim unlocks remain zero on the 130-field target subset.
- The measured fresh perception P95 alone exceeds the 5-second end-to-end target.
- Real package-to-claim binding and independent field review are unavailable; external identities need authority.
- Technical accuracy, HITL and STP ceilings have not been established. The project is not closed.

## Latest measured engineering results

The same 130-field subset now has technical distances 0: 0, 1: 1, 2: 9, 3: 5, 4+: 5. These are target-field distances, not complete real-claim unlocks. Evidence review remains 122/130; total review remains 122/130; CDP-controlled review remains 59/130. Real claim HITL and STP remain null.

Noncanonical discovery: 66 alternatives on 38/100 OTHER pages, including 30 NPI alternatives. All are UNVERIFIED_DISCOVERY, outside canonical decisions. The cohort excludes every package in the blind review manifest; no labels were generated.

CPU arena paired experiment (12 identical pages, eight threads, one worker): P50 10366.97 to 4037.25 ms; P95/P99 16375.28 to 5827.47 ms; throughput 0.1038 to 0.2487 pages/sec. Token text, geometry, confidence, candidate and identity outputs matched exactly. Peak RSS increased from 180MB to 1.40GB. Cold model load increased from 597 to 1262 ms and is excluded from these page timings. This native runtime option is default-off.

A later repeat with the same arena and default batch size measured P50 4454.72 ms, P95/P99 8993.47 ms and throughput 0.2051 pages/sec. Observed P95 5.83-8.99 seconds does not qualify a reliable eight-second or five-second target. Complete end-to-end latency remains unevaluated. Recognition batches 3 and 12 changed evidence and were slower; neither was retained.

The independent all-field diagnostic covers 200 frozen fields: R@1 66%, R@3/R@5 81.5%. It identifies 37 missing reference candidates, 31 ranking misses and 40 fields without a shadow structural validator. It does not replace the historical 130-field denominator or become release truth.

Local OCR experiments made one fresh OCR call/page, zero LLM calls and zero paid AI calls. Infrastructure cost and complete processing cost/page are not measured.

## Current architecture bottleneck

Perception: source-token geometry and label ownership defects repaired; real extraction correctness remains unverified. Candidate generation: missing alternatives remain. Ranking: plausible name alternatives remain unresolved. Validation: provider datatype corrected; 40 all-field structural results remain unknown, not passes. Evidence: no independent source-bound truth or identity authority. Decision: fail-closed policy retained. Latency: recognition dominates and the five-second end-to-end target remains unqualified.

## Next action executed

Executed all-field candidate decomposition to locate the remaining candidate and ranking gaps without changing the historical denominator. Next unresolved work is source-bound candidate coverage and ranking; no technical ceiling is proven.

Git publication remains externally blocked: origin returned HTTP 403 because ashishdat lacks write access to ashneevai/CDP. Local commits are preserved on closure/cdp-target.
