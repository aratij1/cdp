# CDP Phase 7A.14 UB Service Lines

```json
{
  "before_frozen": {
    "truth_rows": 6,
    "reconstructed_rows": 0,
    "accuracy": 0.0
  },
  "implementation": {
    "engine": "UB04ServiceLineEngine",
    "candidate_component": "UB04ServiceLineExtractor",
    "fallback_order": [
      "DETERMINISTIC_LINE_GRID",
      "OCR_TOKEN_GEOMETRY",
      "PROJECTION_PROFILE_DIAGNOSTIC",
      "CONNECTED_COMPONENT_DIAGNOSTIC"
    ],
    "regional_ocr_calls_per_table": 1,
    "docling_runtime_calls": 0,
    "row_object_fields": [
      "revenue_code",
      "description",
      "hcpcs",
      "service_date",
      "units",
      "charge",
      "row_bbox",
      "column_bboxes",
      "ocr_candidates",
      "validation_status",
      "reconstruction_confidence"
    ],
    "validation": [
      "revenue_code",
      "HCPCS",
      "date",
      "units",
      "currency",
      "row_completeness",
      "claim_total_reconciliation"
    ],
    "runtime_promotion": false
  },
  "after": "NOT_MEASURABLE_NO_TUNING_SERVICE_LINE_TRUTH",
  "observation_only_run": "NOT_RUN"
}
```
