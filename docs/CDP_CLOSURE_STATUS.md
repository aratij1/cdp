# CDP closure status

PROJECT STATUS: CONTINUE

Production authority remains disabled. No closure gate is qualified.

The local CDP2 commit is preserved on closure/cdp-target. Origin is ashneevai/CDP.

## Current evidence

Frozen regression: 20 claims / 130 fields; 110 technical blockers, 122 evidence blockers; 59 CDP-controlled review fields. These are not release scores.

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

Validation: {"NEW_SEMANTIC_REGRESSIONS": 0, "OTHER_UNKNOWN_canonical_localization": 0, "architecture": "PASS", "baseline_environment_issue": "Four historical failures caused only by CRLF checkout bytes, repaired without changing frozen content", "compose": "PASS", "diff_check": "PASS", "failures": 0, "false_ub04_canaries": "3/3 PASS", "full_suite_passed": 1430, "full_suite_skipped": 6, "mypy": "PASS 10 files", "ruff": "PASS"}


## Fresh perception runtime

Includes decode, preprocessing, fresh OCR, strict routing and spatial extraction. Excludes complete claim processing and model cold start; those targets remain unqualified.

| Threads | Pages | P50 ms | P95 ms | P99 ms | Pages/sec |
|---|---:|---:|---:|---:|---:|
| 8 | 12 | 11395.94 | 16175.51 | 16175.51 | 0.0956 |
| 4 | 12 | 15270.85 | 21316.53 | 21316.53 | 0.0735 |

## Exact remaining gaps

- Regression Recall@5 is 76.15%, below the candidate-recall target; no real release recall is available.
- Technical blockers and engineering claim unlocks remain unchanged on the frozen cohort.
- The measured fresh perception P95 alone exceeds the 5-second end-to-end target.
- Real package-to-claim binding and independent field review are unavailable; external identities need authority.
- Technical accuracy, HITL and STP ceilings have not been established. The project is not closed.
