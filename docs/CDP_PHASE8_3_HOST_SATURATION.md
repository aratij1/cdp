# CDP Phase 8.3 Host Saturation

| Workers | pages/min | P50 s | P95 s | P99 s | Peak GiB | Host CPU | Efficiency |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5.642 | 10.16 | 15.66 | 18.04 | 0.927 | 44.69% | 100.00% |
| 2 | 5.619 | 21.22 | 30.29 | 35.15 | 1.394 | 64.76% | 49.79% |
| 4 | 4.837 | 47.68 | 74.25 | 84.28 | 1.920 | 73.71% | 21.43% |
| 8 | 4.389 | 103.98 | 168.35 | 193.17 | 2.704 | 70.95% | 9.72% |

Classification: **HOST_CPU_SATURATED**. Same-host worker count is not a cluster-scaling proxy; throughput declines while latency and memory rise.
