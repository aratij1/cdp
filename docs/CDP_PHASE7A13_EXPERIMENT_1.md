# CDP Phase 7A.13 Experiment 1

```json
{
  "experiment_id": "EXP-7A13B-01-TEMPLATE-REGISTRATION-EVIDENCE",
  "hypothesis": "Existing template-registration evidence can safely resolve the largest remaining tuning-only standard-verification fallback category without threshold changes.",
  "selected_from_tuning_pareto": {
    "category": "SAFE_FALLBACK",
    "count": 390,
    "percent_total_errors": 0.45614035087719296,
    "cumulative_percent": 0.45614035087719296,
    "families_affected": [
      "CMS1500",
      "UB04"
    ],
    "datasets_affected": [
      "PRODUCTION_HOLDOUT_V2_REPRESENTATIVE",
      "ROUTING_DEV_V2",
      "ROUTING_DEV_V4_REMEDIATION_01",
      "SYNTHETIC_PUBLIC_V1",
      "SYNTHETIC_PUBLIC_V2",
      "SYNTHETIC_PUBLIC_V3"
    ],
    "tuning_permitted_count": 93,
    "observation_only_count": 297
  },
  "excluded_historical_or_out_of_scope_categories": {
    "GEOMETRY_FAILURE": "REM-01 content-bound geometry was previously rejected",
    "CUSTOM_STRUCTURE_FAILURE": "not a standard verification failure"
  },
  "tuning_data_used": 430,
  "observation_data_used_for_selection": 0,
  "files_changed": [
    "evaluation/engineering_benchmark_v1/experiment_1_registration.py"
  ],
  "production_files_changed": [],
  "baseline": {
    "documents": 430,
    "processing_route_accuracy": 0.35348837209302325,
    "standard_fixed_route_recall": 0.15,
    "cms_fixed_route_recall": 0.2636363636363636,
    "ub_fixed_route_recall": 0.06666666666666667,
    "false_standard_authorization_rate": 0.0,
    "safe_fallback_count": 93
  },
  "candidate": {
    "documents": 430,
    "processing_route_accuracy": 0.35348837209302325,
    "standard_fixed_route_recall": 0.15,
    "cms_fixed_route_recall": 0.2636363636363636,
    "ub_fixed_route_recall": 0.06666666666666667,
    "false_standard_authorization_rate": 0.0,
    "safe_fallback_count": 93
  },
  "absolute_processing_route_gain": 0.0,
  "absolute_target_recall_gain": 0.0,
  "cost": {
    "registration_calls": 132,
    "registration_method_counts": {
      "rescale_only_alignment_failed": 132
    },
    "added_latency_ms": {
      "p50": 1685.9985000046436,
      "p95": 2079.3820999970194,
      "p99": 2519.8340000060853
    }
  },
  "tuning_gate": {
    "processing_route_gain_gte_2pp": false,
    "standard_fixed_route_recall_gain_gte_2pp": false,
    "false_standard_authorization_no_material_regression": true,
    "cms_does_not_regress": true,
    "ub_does_not_regress": true,
    "added_p95_lte_20pct_of_baseline_route_p95": false
  },
  "observation_only_result": {
    "status": "NOT_RUN_TUNING_GATE_FAILED"
  },
  "decision": "REJECT",
  "stop_after_experiment_1": true
}
```
