# CDP Phase 8.4 Production Evidence Coverage Report

## Result

Phase 8.4 improved safe field coverage from 29.79% to 66.21% and reduced field HITL from 70.21% to 33.79% without rerunning OCR or changing the frozen extraction frontier. Accepted precision is 100%; total and critical false accepts are both zero.

| Metric | Profile A | Profile B | Profile C |
|---|---:|---:|---:|
| Accepted fields | 283 | 283 | 629 |
| Correct accepted | 283 | 283 | 629 |
| Incorrect accepted | 0 | 0 | 0 |
| Accepted precision | 100.00% | 100.00% | 100.00% |
| Safe field coverage | 29.79% | 29.79% | 66.21% |
| Field HITL | 70.21% | 70.21% | 33.79% |
| Critical field HITL | 100.00% | 100.00% | 56.00% |
| Review fields/page | 6.67 | 6.67 | 3.21 |
| Claim HITL | 100.00% | 100.00% | 100.00% |
| Claim STP | 0.00% | 0.00% | 0.00% |
| False accepts | 0 | 0 | 0 |
| Critical false accepts | 0 | 0 | 0 |

Profile A reproduces the frozen Phase 8.3 baseline exactly. Profile B proves the corrected E3 meaning without changing decisions. Profile C adds only qualified E3, deterministic E4, truth-blind E6, explicit field policy, alias governance, and reachable field-specific combinations.

The first 70% coverage / 30% field-HITL target was not forced. The achieved frontier is 3.79 percentage points short because additional promotions would require unsupported critical-field corroboration. Claim STP remains blocked by the Pareto described in `CDP_PHASE8_4_CLAIM_BLOCKER_PARETO.md`.

## Economics

The replay invokes no OCR, secondary OCR, reference service, or cloud model. Common-path cloud cost remains $0.00 and machine extraction cost remains the frozen Phase 8.3 estimate of approximately $0.00059/page.

Using the Phase 8.3 observed HITL unit economics, reducing review tasks from 6.67 to 3.21 per page projects field-review cost from $0.301042/page to approximately $0.145/page. This is a planning estimate, not a measured invoice. Claim-level HITL incidence remains 100%, so workflow overhead not represented by per-field review pricing is unchanged.

## Gates

- Frozen extraction component hashes persisted at commit `6060e0f13a69ecf24dd7ba07f73242a4d82aedc3`.
- Frozen replay input ID: `PHASE8_4_POLICY_REPLAY_INPUT_V1`.
- OCR reruns: 0.
- Extraction output digest identical across A/B/C.
- Evaluation-only evidence leaks: 0.
- Forbidden-route accepts: 0.
- Unexpected unreachable Profile C policies: 0.
- Common-path cloud cost: $0.
