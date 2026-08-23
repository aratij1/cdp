# CDP Phase 7A.13 Verifier Report

```json
{
  "all": {
    "CMS1500": {
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
    "UB04": {
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
    }
  },
  "tuning_permitted": {
    "CMS1500": {
      "positive_pages": 110,
      "hard_negative_pages": 320,
      "precision": 0.5454545454545454,
      "recall": 0.32727272727272727,
      "false_verification_rate": 0.09375,
      "not_verified_rate": 0.0,
      "ambiguous_rate": 0.6727272727272727,
      "true_verified": 36,
      "false_verified": 30,
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
        }
      }
    },
    "UB04": {
      "positive_pages": 150,
      "hard_negative_pages": 280,
      "precision": 1.0,
      "recall": 0.06666666666666667,
      "false_verification_rate": 0.0,
      "not_verified_rate": 0.02,
      "ambiguous_rate": 0.9133333333333333,
      "true_verified": 10,
      "false_verified": 0,
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
        }
      }
    }
  },
  "observation_only": {
    "CMS1500": {
      "positive_pages": 300,
      "hard_negative_pages": 500,
      "precision": 0.5159010600706714,
      "recall": 0.4866666666666667,
      "false_verification_rate": 0.274,
      "not_verified_rate": 0.0,
      "ambiguous_rate": 0.5133333333333333,
      "true_verified": 146,
      "false_verified": 137,
      "by_dataset": {
        "PRODUCTION_HOLDOUT_V2_REPRESENTATIVE": {
          "positive_pages": 180,
          "negative_pages": 320,
          "precision": 0.5214285714285715,
          "recall": 0.8111111111111111,
          "false_verification_rate": 0.41875,
          "not_verified_rate": 0.0,
          "ambiguous_rate": 0.18888888888888888
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
    "UB04": {
      "positive_pages": 360,
      "hard_negative_pages": 440,
      "precision": 0.9851851851851852,
      "recall": 0.36944444444444446,
      "false_verification_rate": 0.004545454545454545,
      "not_verified_rate": 0.08055555555555556,
      "ambiguous_rate": 0.55,
      "true_verified": 133,
      "false_verified": 2,
      "by_dataset": {
        "PRODUCTION_HOLDOUT_V2_REPRESENTATIVE": {
          "positive_pages": 180,
          "negative_pages": 320,
          "precision": 0.9851851851851852,
          "recall": 0.7388888888888889,
          "false_verification_rate": 0.00625,
          "not_verified_rate": 0.09444444444444444,
          "ambiguous_rate": 0.16666666666666666
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
    }
  }
}
```
