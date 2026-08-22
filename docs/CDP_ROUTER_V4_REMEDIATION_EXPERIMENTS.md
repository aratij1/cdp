# Router V4 remediation experiments

Baseline: 11% accuracy, CMS 18.33%, UB 2%, P50/P95 490/1,022 ms, one OCR call, zero false standard routes.

| Experiment | CMS recall | UB recall | True / false recoveries | Precision | P95 | Decision |
|---|---:|---:|---:|---:|---:|---|
| REM-01 content geometry | 23.33% (+5) | 7% (+5) | 9 / 1 | 100% | 1,074 ms | REJECT |
| REM-02 token groups only | 20% (+1.67) | 2% (+0) | 1 / 0 | 100% | 1,425 ms | REJECT |
| REM-COMBINED-01 | 23.33% | 7% | diagnostic only | 100% | 1,826 ms | REJECT |

REM-01 has eight unique recoveries; REM-02 has zero; one overlaps. Neither meets the +10-point CMS and UB gate. Production/default V4 remains unchanged through disabled experiment flags.

