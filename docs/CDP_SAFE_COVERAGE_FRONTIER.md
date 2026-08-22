# CDP Safe-Coverage Frontier

> Synthetic development replay. Oracle rows are upper bounds, not implemented production evidence.

| Evidence | Safe coverage | Est. final field HITL | Unresolved automation | Est. critical HITL | Claim STP | False accepts | Extra OCR | Est. mean latency | Est. P95 | Qualification |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| E1 | 0.00% | 100.00% | 100.00% | 100.00% | 0.00% | 0 | 0 | 352.6 ms | 750.0 ms | MEASURED |
| E1+E3 | 0.00% | 100.00% | 100.00% | 100.00% | 0.00% | 0 | 0 | 352.6 ms | 750.0 ms | MEASURED_SYNTHETIC_STRUCTURE |
| E1+E3+E4 | 0.00% | 100.00% | 91.50% | 100.00% | 0.00% | 0 | 0 | 352.6 ms | 750.0 ms | CURRENT_BASELINE |
| E1+E2+E3+E4 | 85.83% | 14.17% | 8.50% | 14.17% | 80.00% | 0 | 600 | 967.8 ms | 2571.9 ms | MEASURED_CONFIRMATION_COUNTERFACTUAL |
| E1+E3+E4+E6 | 0.00% | 100.00% | 91.50% | 100.00% | 0.00% | 0 | 0 | 352.6 ms | 750.0 ms | CURRENTLY_COMPUTABLE |
| E1+E2+E3+E4+E6 | 85.83% | 14.17% | 8.50% | 14.17% | 80.00% | 0 | 600 | 967.8 ms | 2571.9 ms | MEASURED_CONFIRMATION_COUNTERFACTUAL |
| +E5 oracle | 62.67% | 37.33% | 27.50% | 37.33% | 0.00% | 0 | 0 | 352.6 ms | 750.0 ms | ORACLE_CEILING_NOT_IMPLEMENTED |
| +E7 oracle | 99.33% | 0.67% | 0.50% | 0.67% | 96.67% | 0 | 0 | 352.6 ms | 750.0 ms | ORACLE_CEILING_NOT_IMPLEMENTED |
