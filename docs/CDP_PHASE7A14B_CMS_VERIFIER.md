# CDP Phase 7A.14B CMS Verifier



```json
{
  "before": {
    "positive_pages": 410,
    "hard_negative_pages": 820,
    "precision": 0.5214899713467048,
    "recall": 0.44390243902439025,
    "false_verification_rate": 0.20365853658536584,
    "not_verified_rate": 0.0,
    "ambiguous_rate": 0.5560975609756098,
    "true_verified": 182,
    "false_verified": 167,
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
        "precision": 0.5214285714285715,
        "recall": 0.8111111111111111,
        "false_verification_rate": 0.41875,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 0.18888888888888888
      },
      "ROUTING_DEV_V2": {
        "positive_pages": 40,
        "negative_pages": 83,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.3614457831325301,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 1.0
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
        "positive_pages": 60,
        "negative_pages": 140,
        "precision": 1.0,
        "recall": 0.43333333333333335,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 0.5666666666666667
      },
      "SYNTHETIC_PUBLIC_V1": {
        "positive_pages": 60,
        "negative_pages": 60,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.05,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 1.0
      },
      "SYNTHETIC_PUBLIC_V2": {
        "positive_pages": 60,
        "negative_pages": 60,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 1.0
      },
      "SYNTHETIC_PUBLIC_V3": {
        "positive_pages": 0,
        "negative_pages": 60,
        "precision": 0.0,
        "recall": 0.0,
        "false_verification_rate": 0.0,
        "not_verified_rate": 0.0,
        "ambiguous_rate": 0.0
      }
    }
  },
  "after": "CONTRADICTION_REASON_SEMANTICS_REFACTORED; THRESHOLDS_UNCHANGED; NOT_PROMOTED",
  "identity_separate_from_geometry": true,
  "contradictions_block_verification": true,
  "global_threshold_lowered": false
}
```
