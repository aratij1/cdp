# CDP review Pareto

This Pareto uses the last governed development evaluation: 262 fields formerly sent to review. Reasons are multi-label, so counts do not sum to 262.

| Rank | Review reason | Fields | Share | Primary remediation |
|---:|---|---:|---:|---|
| 1 | OCR disagreement | 201 | 76.72% | Field-specific OCR selection and consensus calibration |
| 2 | No evidence | 171 | 65.27% | Crop/registration repair and evidence completeness |
| 3 | Address ambiguous | 154 | 58.78% | Address parsing and governed reference matching |
| 4 | Empty crop | 137 | 52.29% | Registration quality and wrong-crop protection |
| 5 | Low registration confidence | 122 | 46.56% | Per-form homography calibration |
| 6 | Low OCR confidence | 118 | 45.04% | Field-type preprocessing/engine routing |
| 7 | Invalid format | 91 | 34.73% | Normalization plus semantic validation |
| 8 | Unstructured document | 91 | 34.73% | Dedicated unstructured route |
| 9 | Multiple plausible values | 85 | 32.44% | Reference-backed candidate ranking |
| 10 | Critical name unverified | 60 | 22.90% | Exact/phonetic reference evidence, fail closed |

The leading fields are `patient_last_name` and `patient_first_name` (30 each), followed by patient and insured address-line-2 fields (24 each). The safe measured reduction is currently zero: no review is removed until a governed experiment preserves zero false accepts and does not regress critical accuracy.

At the configured $1.00 reviewed-page labor assumption, current total cost is $0.76936/page: $0.00210 routing, $0.00010 compute, $0.00050 storage/orchestration, and $0.76667 HITL. Review rates of 30%, 10%, and 5% imply approximately $0.30270, $0.10270, and $0.05270/page respectively, before any additional model-call cost. These are planning scenarios, not achieved results.
