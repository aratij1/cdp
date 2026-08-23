# CDP Phase 7A.14B UB Verifier



```json
{
  "before": {
    "positive_pages": 510,
    "hard_negative_pages": 720,
    "precision": 0.9862068965517241,
    "recall": 0.2803921568627451,
    "false_verification_rate": 0.002777777777777778,
    "not_verified_rate": 0.06274509803921569,
    "ambiguous_rate": 0.6568627450980392,
    "true_verified": 143,
    "false_verified": 2,
    "by_dataset": {
      "BUNDLE_D_DEV_V1": {
        "positive_pages": 0,
        "negative_pages": 27,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 0.0
      },
      "PRODUCTION_HOLDOUT_V2_REPRESENTATIVE": {
        "positive_pages": 180,
        "negative_pages": 320,
        "precision": 0.9851851851851852,
        "recall": 0.7388888888888889,
        "false_verification_rate": 0.00625,
        "not_verified_rate": 0.09444444444444444,
        "ambiguous_rate": 0.16666666666666666
      },
      "ROUTING_DEV_V2": {
        "positive_pages": 40,
        "negative_pages": 83,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.075,
        "ambiguous_rate": 0.925
      },
      "ROUTING_DEV_V3": {
        "positive_pages": 10,
        "negative_pages": 70,
        "precision": 1.0,
        "recall": 1.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 0.0
      },
      "ROUTING_DEV_V4_REMEDIATION_01": {
        "positive_pages": 100,
        "negative_pages": 100,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 1.0
      },
      "SYNTHETIC_PUBLIC_V1": {
        "positive_pages": 60,
        "negative_pages": 60,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 1.0
      },
      "SYNTHETIC_PUBLIC_V2": {
        "positive_pages": 60,
        "negative_pages": 60,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.1,
        "ambiguous_rate": 0.9
      },
      "SYNTHETIC_PUBLIC_V3": {
        "positive_pages": 60,
        "negative_pages": 0,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.1,
        "ambiguous_rate": 0.9
      }
    }
  },
  "after": "CONTRADICTION_REASON_SEMANTICS_REFACTORED; THRESHOLDS_UNCHANGED; NOT_PROMOTED",
  "precision_preservation_required": true,
  "global_threshold_lowered": false
}
```
