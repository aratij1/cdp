# CDP Phase 7A.14 Latency Pareto

```json
{
  "frozen_routing_latency_ms": {
    "p50": 2466.186599995126,
    "p95": 57902.358999999706,
    "p99": 178490.96490000375,
    "mean": 10371.242021056643
  },
  "frozen_tuning_routing_latency_ms": {
    "p50": 1734.5332000113558,
    "p95": 3324.59530000051,
    "p99": 4255.22269999783,
    "mean": 1932.68495651096
  },
  "registration_precheck_latency_ms": {
    "p50": 4560.403699986637,
    "p95": 9397.287600004347,
    "p99": 12169.612900004722
  },
  "full_page_ocr_calls_per_page": 1.0,
  "stage_findings": {
    "document_preprocessing": "INCLUDED_IN_ROUTE_PREPROCESS_STAGE",
    "full_page_ocr": "ONE_CALL_PER_TUNING_PAGE",
    "classification_nomination_verification": "INSTRUMENTED_IN_FROZEN_ROUTING_ROWS",
    "registration": "SIFT_SKIPPED_FOR_INCOMPATIBLE_TEMPLATE_LINEAGES",
    "regional_ocr": "NOT_RUN_NO_TUNING_FIELD_TRUTH",
    "retries": "ZERO_IN_PHASE7A14_DIAGNOSTIC",
    "subprocess_startup": "TESSERACT_IS_ONE_CHILD_PROCESS_PER_FULL_PAGE_CALL",
    "rapidocr_initialization": "LAZY_AND_REUSED_PER_LONG_LIVED_EXTRACTOR_INSTANCE",
    "paddle_initialization": "LAZY_AND_REUSED_PER_LONG_LIVED_EXTRACTOR_INSTANCE",
    "template_descriptors": "NOT_COMPUTED_WHEN_COMPATIBILITY_IS_INCOMPATIBLE",
    "file_io": "INCLUDED_IN_REGISTRATION_PRECHECK_LATENCY"
  },
  "fixed_form_candidate_p50_ms": "NOT_MEASURABLE",
  "fixed_form_candidate_p95_ms": "NOT_MEASURABLE",
  "fixed_form_candidate_p99_ms": "NOT_MEASURABLE"
}
```
