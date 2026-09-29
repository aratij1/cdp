# Hard-15 charge miss triage (vs v12.3h)

Reference predictions from `hackathon_300_cascade_v12_3h`. All 9 labeled charges were `AUTO_ACCEPTED` with `LINE_TOTALS_RECONCILED`; box-28 OCR is often empty/garbage so line-sum wins.

| claim | GT | pred | class | note |
| --- | ---: | ---: | --- | --- |
| M048DJJM.036 | 270.00 | 424.00 | wrong line-sum | rapidocr+LINE_TOTALS; GT also line_sum — line set/OCR diverge |
| M048EJGE.021 | 400.00 | 400.00 | OK | |
| M048EJG7.036 | 165.00 | 165.00 | OK | |
| M048DJKH.004 | 233.00 | 222.00 | near-miss / digit | 233↔222 |
| M048DJKN.003 | 22.00 | 200.00 | digit-drop twin | 22↔200 |
| M048DJKN.009 | 600.00 | 1600.00 | digit-inflate twin | 600↔1600 |
| M048EJGE.033 | 500.00 | 200.00 | wrong line-sum | box-28 OCR empty (`.`) |
| M048EJI2.017 | 135.00 | 131.00 | near-miss / digit | 135↔131 |
| M048EJI2.044 | 970.00 | 1455.00 | wrong line-sum / inflate | |

**Implication for corroboration tighten:** do not AUTO on single-engine `LINE_TOTALS_RECONCILED` when dual-engine/DI disagree or digit-twin residual exists; keep HITL unless DI currency-shaped agrees within tolerance or paddle+rapid twin the same sum.
