# Phase 8.11 Competition Scorecard

Decision: **NEEDS_MORE_DATA**. Baseline reproduction: **PASS**. Locked holdout: **SEALED**.

| metric | result | target |
|---|---|---|
| Overall accuracy | 89.05% | >=92% |
| CMS accuracy | 88.74% | >=93% |
| UB accuracy | 89.42% | >=92% |
| Critical accuracy | 91.67% | >=95% |
| Claim STP | 0.00% | evidence-safe |
| Claim HITL | 100.00% | <=20% stretch |
| Fully loaded/page | $0.3876 | <=$0.10 |
| Critical false accepts | 0 | 0 |

Promotion gates:

| gate | passed |
|---|---|
| overall_accuracy_ge_92 | False |
| cms_accuracy_ge_93 | False |
| ub_accuracy_ge_92 | False |
| critical_accuracy_ge_95 | False |
| wrong_crop_recall_ge_90 | False |
| wrong_crop_precision_ge_99 | True |
| usable_localization_ge_95 | False |
| critical_usable_localization_ge_97 | False |
| accepted_precision_ge_99_5 | True |
| critical_false_accepts_zero | True |
| fully_loaded_cost_le_0_10 | False |
| common_path_cloud_cost_zero | True |
| throughput_output_parity | True |
| stage_p95_le_8_seconds | False |
| locked_holdout_sealed | True |
