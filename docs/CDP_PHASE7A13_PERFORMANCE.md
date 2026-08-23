# CDP Phase 7A.13 Performance

```json
{
  "evidence_class": "ENGINEERING_BENCHMARK_ONLY",
  "production_promotion_authority": false,
  "documents": 1230,
  "wall_seconds_this_run": 848.3154993999924,
  "throughput_pages_per_second_this_run": 0.5457875051528313,
  "orchestrator_cpu_seconds_this_run": 1.375,
  "child_cpu_seconds_this_run": 0.0,
  "latency_ms": {
    "p50": 2466.186599995126,
    "p95": 57902.358999999706,
    "p99": 178490.96490000375,
    "mean": 10371.242021056643
  },
  "cloud_api_calls": 0,
  "cloud_cost_usd": 0.0,
  "ocr_engine": "Tesseract 5.x PSM 11",
  "ocr_calls_per_page": 1.0,
  "notes": [
    "CPU values cover only the current invocation; reused checkpoints are excluded.",
    "Tesseract child CPU accounting depends on host OS support."
  ],
  "classification_nomination_verification_latency_ms": {
    "p50": 2466.186599995126,
    "p95": 57902.358999999706,
    "p99": 178490.96490000375,
    "mean": 10371.242021056643
  },
  "registration_ocr_normalization_latency_ms": {
    "CMS1500": {
      "p50": 9900.700699989102,
      "p95": 59998.085100000026,
      "p99": 59998.085100000026
    },
    "UB04": {
      "p50": 9368.011300000944,
      "p95": 31001.793400006136,
      "p99": 31001.793400006136
    }
  },
  "table_reconstruction": {
    "truth_rows": 6,
    "detected_rows": 0
  },
  "mean_cpu_seconds_per_page": "NOT_MEASURABLE_ON_WINDOWS_SUBPROCESS_TREE",
  "mean_cpu_seconds_per_page_note": "Tesseract executes as a child process and the Windows host did not expose child CPU accounting; stage wall latency is measured and no CPU value is fabricated.",
  "memory": "NOT_MEASURABLE_WITHOUT_A_CHILD_PROCESS_PEAK_SAMPLER",
  "nomination_latency": "INCLUDED_IN_ROUTER_NOT_SEPARATELY_INSTRUMENTED",
  "normalization_latency": "INCLUDED_IN_FIELD_EXTRACTION_NOT_SEPARATELY_INSTRUMENTED"
}
```
