# CDP Phase 8.10 — Latency and Cost

| Source | P50 | P95 | P99 | Fully loaded/page |
| --- | ---: | ---: | ---: | ---: |
| SOURCE_A | 7.56 s | 16.53 s | 17.18 s | $0.39008 |
| SOURCE_B | 9.03 s | 12.73 s | 13.92 s | $0.38264 |
| SOURCE_C | 5.58 s | 8.68 s | 15.89 s | $0.38760 |

Worst P95 is 16.53 seconds and misses the 10-second gate. It is also slower than
the Phase 8.9 baseline's 14.53 seconds, so Phase 8.10 makes no latency-improvement
claim. Mean fully loaded cost remains $0.38677/page and misses the $0.20 gate.
Cloud cost is $0. Candidate-level latency was not present in persisted evidence,
so the engine matrix reports that measurement gap instead of fabricating stage
percentiles. Local CPU, memory, and storage were likewise not separately metered.

Cost per safely automated claim is undefined because claim STP is zero. The
reported cost per safely resolved field is $0.00744 under the current evaluation
cost model. Review cost dominates the fully loaded estimate.

The OCR execution boundary now uses a deterministic page/crop/profile/engine/
version cache key. Cache hits return the original evidence provenance and do not
execute the provider again. This protects repeated work but does not retroactively
alter the measured replay latency.

Artifact: `latency_cost.json/csv`.
