# CDP Engineering Routing Confusion Matrix

Evidence class: `ENGINEERING_BENCHMARK_ONLY`. This is not a production holdout or promotion artifact.

Executed 766 of 1230 exact-pixel-unique allowlisted pages. The execution stopped at the largest consecutive deterministic prefix after dense-token anchor reconstruction became operationally unbounded.

## Exact family

| Truth \ Prediction | CMS1500 | NON_CLAIM | UB04 | UNKNOWN_STRUCTURED | UNKNOWN_UNSTRUCTURED |
|---|---:|---:|---:|---:|---:|
| CLAIM_SUPPORT | 0 | 0 | 0 | 0 | 26 |
| CMS1500 | 201 | 0 | 0 | 57 | 8 |
| CUSTOM_INSTITUTIONAL | 0 | 0 | 0 | 3 | 0 |
| CUSTOM_PROFESSIONAL | 0 | 0 | 0 | 33 | 0 |
| NON_CLAIM | 0 | 11 | 0 | 20 | 2 |
| UB04 | 0 | 0 | 218 | 109 | 3 |
| UNKNOWN_STRUCTURED | 0 | 0 | 0 | 50 | 20 |
| UNKNOWN_UNSTRUCTURED | 0 | 0 | 0 | 0 | 5 |

## Canonical processing route

| Truth \ Prediction | CMS_STANDARD_EXTRACTOR | LAYOUT_STRUCTURED_EXTRACTOR | STOP_NON_CLAIM | UB_STANDARD_EXTRACTOR | UNSTRUCTURED_EXTRACTOR |
|---|---:|---:|---:|---:|---:|
| CMS_STANDARD_EXTRACTOR | 54 | 204 | 0 | 0 | 8 |
| LAYOUT_STRUCTURED_EXTRACTOR | 0 | 86 | 0 | 0 | 35 |
| STOP_NON_CLAIM | 0 | 20 | 11 | 0 | 2 |
| UB_STANDARD_EXTRACTOR | 0 | 317 | 0 | 10 | 3 |
| UNSTRUCTURED_EXTRACTOR | 0 | 0 | 0 | 0 | 16 |

The family matrix intentionally treats custom and support pages as distinct truth classes even though the frozen hierarchical baseline currently abstains to `UNKNOWN_STRUCTURED`/`UNKNOWN_UNSTRUCTURED`. Processing compatibility is reported separately.
