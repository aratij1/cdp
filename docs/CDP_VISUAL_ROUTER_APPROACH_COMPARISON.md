# Eligibility approach comparison

| Approach | Worst CMS | Worst UB | Worst structured | Worst non-claim | Safety result |
|---|---:|---:|---:|---:|---|
| A — LightGBM | 76.67% | 92% | 20% | 0% | false eligibility 12.5–14.2% |
| B — Visual | 96.67% | 100% | 100% | 100% | false standard 0.83% — fail |
| C — Deterministic + visual | 33.33% | 100% | 100% | 100% | zero false standard, CMS recall fail |
| D — Deterministic + ML + visual | 33.33% | 100% | 100% | 100% | up to 5.83% false standard — fail |

No approach meets every worst-source and safety gate. Final deterministic routes were never changed.

