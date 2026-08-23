# CDP Phase 7A.13 Extraction Given Truth Route

```json
{
  "evidence_class": "ENGINEERING_BENCHMARK_ONLY",
  "truth_route_forced": true,
  "sample_design": "30 deterministic pages: per family 12 public synthetic + 3 observation-only representative",
  "documents": 30,
  "fields": 204,
  "CMS1500": {
    "documents": 15,
    "fields": 96,
    "field_exact_accuracy": 0.19791666666666666,
    "critical_field_accuracy": 0.3958333333333333,
    "required_field_accuracy": 0.35185185185185186,
    "crop_correctness": 1.0,
    "ocr_accuracy_given_correct_crop": 0.19791666666666666,
    "normalization_accuracy": 0.19791666666666666,
    "parser_accuracy": 0.9375,
    "checkbox_accuracy": 0.0,
    "safe_field_coverage": 0.0,
    "field_hitl_estimate": 1.0,
    "claim_perfect_rate": 0.0,
    "latency_ms": {
      "p50": 9900.700699989102,
      "p95": 59998.085100000026,
      "p99": 59998.085100000026
    }
  },
  "UB04": {
    "documents": 15,
    "fields": 108,
    "field_exact_accuracy": 0.32407407407407407,
    "critical_field_accuracy": 0.38095238095238093,
    "required_field_accuracy": 0.38333333333333336,
    "crop_correctness": 1.0,
    "ocr_accuracy_given_correct_crop": 0.32407407407407407,
    "normalization_accuracy": 0.32407407407407407,
    "parser_accuracy": 0.8148148148148148,
    "checkbox_accuracy": 0.0,
    "safe_field_coverage": 0.0,
    "field_hitl_estimate": 1.0,
    "claim_perfect_rate": 0.0,
    "latency_ms": {
      "p50": 9368.011300000944,
      "p95": 31001.793400006136,
      "p99": 31001.793400006136
    },
    "revenue_code_accuracy": 0.0,
    "hcpcs_accuracy": 0.0,
    "service_date_accuracy": 0.0,
    "units_accuracy": 0.0,
    "charge_accuracy": 0.0,
    "service_line_row_reconstruction_accuracy": 0.0,
    "column_assignment_accuracy": 0.0,
    "claim_total_reconciliation_accuracy": 0.0,
    "truth_service_rows": 6,
    "detected_service_rows": 0
  },
  "CUSTOM_STRUCTURED": {
    "documents": 15,
    "field_label_value_accuracy": 1.0,
    "table_extraction_accuracy": "NOT_MEASURABLE",
    "structured_region_accuracy": "NOT_MEASURABLE",
    "schema_recovery_accuracy": 1.0,
    "unsupported_field_count": 0,
    "docling_required_rate": "NOT_MEASURABLE",
    "layout_failure_rate": 0.0,
    "latency_p95_ms": 642.3971999902278
  },
  "overall_field_accuracy": 0.2647058823529412,
  "critical_field_accuracy": 0.38738738738738737,
  "false_accepts": 0,
  "critical_false_accepts": 0
}
```
