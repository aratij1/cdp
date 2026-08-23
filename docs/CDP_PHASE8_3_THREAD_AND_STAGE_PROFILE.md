# CDP Phase 8.3 OCR Thread and Stage Profile

| Profile | Workers | pages/hour | machine/page | P95 s | GiB | Output status |
|---|---:|---:|---:|---:|---:|---|
| A | 1 | 328.47 | $0.000609 | 15.45 | 0.927 | NOT_PROVEN_AGAINST_DEFAULT |
| B | 1 | 337.31 | $0.000593 | 15.17 | 0.920 | NOT_ESTABLISHED_VOLATILE_FINGERPRINT |
| C | 2 | 406.66 | $0.000492 | 24.26 | 1.511 | NOT_ESTABLISHED_VOLATILE_FINGERPRINT |
| D | 2 | 406.66 | $0.000492 | 24.26 | 1.511 | NOT_ESTABLISHED_VOLATILE_FINGERPRINT |

Promotion decision: **NO_PROMOTION**. Bounded B/C equivalence is necessary but default-A output and canonical-decision equivalence was not captured; frozen runtime threading remains unchanged.

Full-page OCR and field-candidate stage timing, including detector/classifier/recognizer timings exposed by RapidOCR, is persisted in `stage_performance.json`. Direct ONNX Runtime CPU time by internal stage is unavailable; the report preserves measured wall time and overall process CPU instead of inventing attribution. Candidate profiling identifies regional OCR as the dominant component. Graph/anchor/line clustering and ROI resolution are independently timed; token selection, normalization, validation, and reconciliation remain an aggregate residual because the frozen semantic path was not refactored.
