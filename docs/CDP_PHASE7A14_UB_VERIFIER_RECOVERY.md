# CDP Phase 7A.14 UB Verifier Recovery

```json
{
  "before_frozen_all": {
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
  "tuning_diagnostic": {
    "family": "UB04",
    "policy_version": "ub04-verifier-v1",
    "positive_pages": 150,
    "hard_negative_pages": 280,
    "precision": 1.0,
    "recall": 0.06666666666666667,
    "false_verification_rate": 0.0,
    "outcomes": {
      "TRUE_NOT_VERIFIED": {
        "pages": 280,
        "supporting_evidence_frequency": {
          "PAGE_GEOMETRY": 280,
          "INSTITUTIONAL_GRID": 53,
          "REVENUE_SERVICE_REGION": 36,
          "HCPCS_CHARGE_RELATIONSHIP": 36,
          "PAYER_PROVIDER_RELATIONSHIP": 20,
          "DIAGNOSIS_REGION": 20,
          "SPATIAL_RELATIONSHIPS": 20
        }
      },
      "FALSE_NOT_VERIFIED": {
        "pages": 140,
        "supporting_evidence_frequency": {
          "PAGE_GEOMETRY": 140,
          "BILL_AND_STATEMENT_REGIONS": 97,
          "HIGH_VALUE_ANCHORS": 97,
          "PAYER_PROVIDER_RELATIONSHIP": 7,
          "DIAGNOSIS_REGION": 7,
          "SPATIAL_RELATIONSHIPS": 7,
          "INSTITUTIONAL_GRID": 100,
          "REVENUE_SERVICE_REGION": 16,
          "HCPCS_CHARGE_RELATIONSHIP": 16
        }
      },
      "TRUE_VERIFIED": {
        "pages": 10,
        "supporting_evidence_frequency": {
          "PAGE_GEOMETRY": 10,
          "INSTITUTIONAL_GRID": 10,
          "BILL_AND_STATEMENT_REGIONS": 10,
          "PAYER_PROVIDER_RELATIONSHIP": 10,
          "REVENUE_SERVICE_REGION": 10,
          "HCPCS_CHARGE_RELATIONSHIP": 10,
          "DIAGNOSIS_REGION": 10,
          "HIGH_VALUE_ANCHORS": 10,
          "SPATIAL_RELATIONSHIPS": 10
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
