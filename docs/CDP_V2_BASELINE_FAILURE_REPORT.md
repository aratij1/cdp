# CDP V2 Baseline Failure Report

`PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED` is immutable. The recorded sample
contains 200 IDs selected without replacement using seed `62026`; hashes and
all runtime/configuration versions are stored in its baseline manifest.

## Frozen result

| Metric | Result |
|---|---:|
| Routing accuracy | 39.50% |
| Exact field accuracy | 0.234% (10/4,281) |
| Critical accuracy | 0.702% |
| Safe coverage | 0% |
| Field HITL | 100% |
| Claim STP | 0% |
| Claim HITL | 100% |
| False accepts | 0 |
| Mean latency | 64.54 s/document |
| P95 latency | 193.76 s/document |
| Mean CPU | 99.78 CPU-s/document |

Decision: `REJECT`. The zero false-accept result confirms fail-closed safety,
but does not offset the routing, extraction, coverage, and performance failure.
The baseline must never be overwritten or presented as post-recovery evidence.

Machine-readable provenance:
`evaluation_results/PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED/baseline_manifest.json`.
