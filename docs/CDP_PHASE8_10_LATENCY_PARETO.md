# CDP Phase 8.10 — Latency and Cost Pareto

| Source | P50 | P95 | P99 |
|---|---:|---:|---:|
| Source A | 4.675 s | 10.127 s | 11.146 s |
| Source B | 5.103 s | 8.686 s | 8.787 s |
| Source C | 3.208 s | 5.738 s | 15.150 s |

The worst-source P95 target of 10 seconds is missed by 127 ms on Source A. Source C has the largest tail at P99.

Selective regional OCR invoked 67 times across 420 validation regions (15.95%) and produced 24 incremental correct resolutions. Per-invocation latency was not persisted, so stage-level contribution is not claimed. The evaluation path records this as `PER_INVOCATION_LATENCY_NOT_PERSISTED`.

Common-path cloud cost is $0.00/page. The fully loaded estimate, including review, is $0.38760/page. Because claim STP remains 0%, cost per safe STP claim is undefined.
