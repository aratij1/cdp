# CDP Phase 7A.14 CMS Verifier Recovery

```json
{
  "before_frozen_all": {
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
  "tuning_diagnostic": {
    "family": "CMS1500",
    "policy_version": "cms1500-verifier-v1",
    "positive_pages": 110,
    "hard_negative_pages": 320,
    "precision": 0.5454545454545454,
    "recall": 0.32727272727272727,
    "false_verification_rate": 0.09375,
    "outcomes": {
      "TRUE_NOT_VERIFIED": {
        "pages": 290,
        "supporting_evidence_frequency": {
          "PAGE_GEOMETRY": 290,
          "PROVIDER_BILLING_LAYOUT": 52,
          "SPATIAL_RELATIONSHIPS": 52,
          "SERVICE_LINE_GRID": 142
        }
      },
      "FALSE_VERIFIED": {
        "pages": 30,
        "supporting_evidence_frequency": {
          "PAGE_GEOMETRY": 30,
          "SERVICE_LINE_GRID": 30,
          "PROVIDER_BILLING_LAYOUT": 30,
          "SPATIAL_RELATIONSHIPS": 30
        }
      },
      "FALSE_NOT_VERIFIED": {
        "pages": 74,
        "supporting_evidence_frequency": {
          "PAGE_GEOMETRY": 74,
          "PATIENT_INSURED_RELATIONSHIP": 73,
          "CLAIM_DIAGNOSIS_LAYOUT": 26,
          "PROVIDER_BILLING_LAYOUT": 26,
          "HIGH_VALUE_ANCHORS": 73,
          "SPATIAL_RELATIONSHIPS": 26,
          "SERVICE_LINE_GRID": 48
        }
      },
      "TRUE_VERIFIED": {
        "pages": 36,
        "supporting_evidence_frequency": {
          "PAGE_GEOMETRY": 36,
          "PATIENT_INSURED_RELATIONSHIP": 33,
          "CLAIM_DIAGNOSIS_LAYOUT": 36,
          "SERVICE_LINE_GRID": 36,
          "PROVIDER_BILLING_LAYOUT": 36,
          "HIGH_VALUE_ANCHORS": 33,
          "SPATIAL_RELATIONSHIPS": 36
        }
      }
    },
    "identity_registration_separation": {
      "identity_may_be_verified_without_registration": true,
      "fixed_extractor_requires_verified_identity_and_usable_geometry": true,
      "verified_identity_without_geometry_route": "LAYOUT_STRUCTURED_EXTRACTOR"
    },
    "candidate_change": "NONE_TEMPLATE_LINEAGE_BLOCKED"
  },
  "after": "UNCHANGED_NO_SAFE_PROMOTION",
  "reason": "REGISTRATION_EVIDENCE_UNAVAILABLE_FOR_CURRENT_TEMPLATE_LINEAGE"
}
```
