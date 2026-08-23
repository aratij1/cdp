# CDP Phase 7A.13B Engineering Accuracy Report

`ENGINEERING_BENCHMARK_ONLY`; no production-promotion authority. Frozen benchmark: 1,230 unique pages (430 tuning-permitted, 800 observation-only), manifest `f609e7b02da32e720b71a4c0d4e579921deb27c1714054439764ff2bd3520064`.

| Population | Pages | Exact route | Processing route | CMS recall | UB recall | False standard |
|---|---:|---:|---:|---:|---:|---:|
| all | 1230 | 62.20% | 42.76% | 79.27% | 73.33% | 0.00% |
| tuning_permitted | 430 | 46.05% | 35.35% | 74.55% | 33.33% | 0.00% |
| observation_only | 800 | 70.88% | 46.75% | 81.00% | 90.00% | 0.00% |

Truth-route standard extraction is 26.47%; critical accuracy is 38.74%. End-to-end field accuracy is 0.00%. Primary decision: `MULTIPLE_BOTTLENECKS`. UNKNOWN_UNSTRUCTURED has five pages, status `LOW_SAMPLE_SUPPORT`, and is not a release gate.

Experiment 1: `REJECT`. Production runtime remained unchanged.
