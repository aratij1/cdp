# CDP Raw Accuracy Error Pareto

> Synthetic-only diagnostic. This is not production accuracy.

Baseline: **353 / 600 (58.83%)**.
Total errors: **247**.

| Rank | Family | Field | Total | Correct | Wrong | Accuracy | % all errors | Cumulative | Criticality | Blocks STP |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | CMS1500 | `insured_id_number` | 60 | 0 | 60 | 0.00% | 24.29% | 24.29% | C2 | yes |
| 2 | UB04 | `federal_tax_no` | 60 | 0 | 60 | 0.00% | 24.29% | 48.58% | C1 | no |
| 3 | UB04 | `provider_npi` | 60 | 16 | 44 | 26.67% | 17.81% | 66.40% | C1 | no |
| 4 | UB04 | `patient_dob` | 60 | 22 | 38 | 36.67% | 15.38% | 81.78% | C2 | yes |
| 5 | UB04 | `patient_name` | 60 | 38 | 22 | 63.33% | 8.91% | 90.69% | C2 | yes |
| 6 | CMS1500 | `patient_name` | 60 | 39 | 21 | 65.00% | 8.50% | 99.19% | C2 | yes |
| 7 | UB04 | `principal_diagnosis` | 60 | 58 | 2 | 96.67% | 0.81% | 100.00% | C1 | no |
| 8 | CMS1500 | `patient_dob` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C2 | yes |
| 9 | CMS1500 | `total_charge` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C3 | yes |
| 10 | UB04 | `type_of_bill` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C1 | no |
