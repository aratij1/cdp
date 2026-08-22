# CDP V2 Performance Profile

This profile reads the immutable rejected baseline; it does not rerun V2.

| Stage | Total seconds | Mean/document | P95 |
|---|---:|---:|---:|
| OCR | 11,699.95 | 58.50 | 181.69 |
| Classification | 778.48 | 3.89 | 8.67 |
| Registration | 350.90 | 6.38 on routed standards | 11.61 |
| Preparation | 39.72 | 0.20 | 0.50 |
| Layout | 20.98 | 0.14 on Bundle-D pages | 0.33 |
| Evidence | 7.19 | 0.036 | 0.10 |
| Claim decision | 0.24 | 0.001 | 0.004 |

OCR consumed 91% of measured stage wall time. CMS-routed documents averaged
156.37 seconds, compared with 31.29 seconds for unknown-unstructured and 20.58
seconds for unknown-structured. The standard regional OCR call pattern, not
evidence or claim policy, is the dominant CPU and latency bottleneck.

The baseline predates per-call cache telemetry, so repeated-crop counts cannot
be reconstructed honestly. Phase 7 adds versioned content-addressing and call
audits for all future development/profile runs.
