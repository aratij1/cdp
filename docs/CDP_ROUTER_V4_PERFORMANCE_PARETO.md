# Router V4 remediation performance Pareto

| Experiment | Feature bundle mean / P95 | Semantic-anchor mean / P95 | Router mean / P95 | End-to-end P95 |
|---|---:|---:|---:|---:|
| REM-01 | 51 / 67 ms | 89 / 353 ms | 140 / 402 ms | 1,074 ms |
| REM-02 | 62 / 106 ms | 133 / 529 ms | 232 / 631 ms | 1,425 ms |

REM-01 added about 51 ms at end-to-end P95 for four net recoveries over 200 pages. REM-02 added about 403 ms at P95 for one recovery. Token-group processing also increases downstream semantic-anchor work and is rejected.

