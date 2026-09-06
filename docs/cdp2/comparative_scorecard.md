# CDP 2.0 architecture comparison

CDP2_NO_ARCHITECTURAL_GAIN

20 identical claims, 20 observed page hashes, 130 fields. Both paths use frozen candidate observations.
Package lineage for the frozen cohort is unavailable; release holdout overlap cannot be certified.
Latency below is milliseconds per claim for cached decision replay, including legacy work plus shadow overhead.
No fresh-OCR performance target or real accuracy improvement is claimed.

| Metric | Legacy | CDP 2.0 | Delta | Authority |
|---|---:|---:|---:|---|
| technical_blockers | 110 | 110 | 0 | FROZEN_REGRESSION |
| evidence_blockers | 122 | 122 | 0 | FROZEN_REGRESSION |
| critical_blockers | 20 | 20 | 0 | FROZEN_REGRESSION |
| technical_unlock_distance | 110 | 110 | 0 | FROZEN_REGRESSION |
| production_unlock_distance | 232 | 232 | 0 | FROZEN_REGRESSION |
| engineering_unlockable | 0 | 0 | 0 | FROZEN_REGRESSION |
| production_unlockable | 0 | 0 | 0 | FROZEN_REGRESSION |
| CDP_CONTROLLED_HITL | 59 | 59 | 0 | FROZEN_REGRESSION |
| technical_hitl | 59 | 59 | 0 | FROZEN_REGRESSION |
| evidence_hitl | 122 | 122 | 0 | FROZEN_REGRESSION |
| total_hitl | 122 | 122 | 0 | FROZEN_REGRESSION |
| candidate_ambiguity | 39 | 39 | 0 | FROZEN_REGRESSION |
| wrong_crop_dependence | 21 | 21 | 0 | FROZEN_REGRESSION |
| missing_crop_dependence | 17 | 17 | 0 | FROZEN_REGRESSION |
| P50 | 0.708100 | 1.323400 | 0.615300 | MEASURED_MS_PER_CLAIM_CACHED |
| P95 | 4.105000 | 4.788600 | 0.683600 | MEASURED_MS_PER_CLAIM_CACHED |
| P99 | 5.526200 | 6.617200 | 1.091000 | MEASURED_MS_PER_CLAIM_CACHED |
| throughput_claims_per_second | 910.792436 | 583.582087 | -327.210349 | MEASURED_MS_PER_CLAIM_CACHED |
| OCR_calls/page | 0 | 0 | 0 | NO_NEW_CALLS_IN_CACHED_REPLAY |
| regional_OCR_calls/page | 0 | 0 | 0 | NO_NEW_CALLS_IN_CACHED_REPLAY |
| LLM_calls/page | 0 | 0 | 0 | NO_NEW_CALLS_IN_CACHED_REPLAY |
| paid_AI_cost/page | 0 | 0 | 0 | NO_NEW_CALLS_IN_CACHED_REPLAY |
| accuracy | null | null | null | NOT_EVALUABLE_NO_TRUSTED_TRUTH |
| critical_accuracy | null | null | null | NOT_EVALUABLE_NO_TRUSTED_TRUTH |
| accepted_precision | null | null | null | NOT_EVALUABLE_NO_TRUSTED_TRUTH |
| critical_false_accepts | null | null | null | NOT_EVALUABLE_NO_TRUSTED_TRUTH |
| engineering_claims_unlocked | 0 | 0 | 0 | NEW_TECHNICAL_UNLOCKS_RELATIVE_TO_LEGACY |

Safety: OTHER/UNKNOWN canonical localization = 0; false UB04 canaries = 3/3 PASS.
Production canonical outputs remain unchanged; runtime_authority = false.

Validation: 1,337 passed; 45 focused tests passed. Baseline: 1,297 passed.
NEW_SEMANTIC_REGRESSIONS = 0; pre-existing failures = 0; environment failures = 0.
Ruff, scoped mypy, architecture validation, Docker Compose config, and diff checks pass.

Separate real inventory: 1,000 assets / 2,173 pages / 110 packages; 100 pages operationally profiled.
150 pages selected for review; operational-sample packages excluded. Share only active_learning_blind_manifest.json with blind reviewers.
