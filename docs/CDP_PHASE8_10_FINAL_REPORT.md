# CDP Phase 8.10 — Final Report

Decision: `NEEDS_MORE_DATA`.

The revised production path achieves 97.86% expected-value containment, 6.43% over-crop, 89.05% overall final accuracy, 91.67% critical accuracy, 100% accepted precision, zero critical false accepts, and $0 common-path cloud cost.

It does not meet production-usable localization (87.86%), wrong-crop recall (45.10%), CMS/UB 90% accuracy, critical 95% accuracy, or worst-source P95 below 10 seconds. No promotion is claimed.

Claim STP remains 0%, claim HITL is 100%, and field HITL is 91.33%. Selective regional OCR ran for 67 of 420 validation fields (15.95%) and added 24 correct resolutions. UB service-line row detection is 100%, exact-row accuracy is 68.54%, and column-cell accuracy is 85.02%.

The Phase 8.9 baseline and hashes are frozen under `evaluation_results/phase8_10/baseline/`. The locked holdout was not accessed. Runtime/evaluation parity passes, secondary provenance coverage is 100%, unknown dependency is 0%, and no new model, router, or decision-policy tuning was introduced.

See:

- `CDP_PHASE8_10_REGION_PRECISION.md`
- `CDP_PHASE8_10_WRONG_CROP_PARETO.md`
- `CDP_PHASE8_10_EXTRACTION_PARETO.md`
- `CDP_PHASE8_10_LATENCY_PARETO.md`
- `CDP_PHASE8_10_RUNTIME_PARITY.md`
