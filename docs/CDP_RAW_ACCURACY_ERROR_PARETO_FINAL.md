# CDP Raw Accuracy Error Pareto

> Synthetic-only diagnostic. This is not production accuracy.

Baseline: **594 / 600 (99.00%)**.
Total errors: **6**.

| Rank | Family | Field | Total | Correct | Wrong | Accuracy | % all errors | Cumulative | Criticality | Blocks STP |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|
| 1 | CMS1500 | `patient_name` | 60 | 57 | 3 | 95.00% | 50.00% | 50.00% | C2 | yes |
| 2 | UB04 | `federal_tax_no` | 60 | 58 | 2 | 96.67% | 33.33% | 83.33% | C1 | no |
| 3 | CMS1500 | `insured_id_number` | 60 | 59 | 1 | 98.33% | 16.67% | 100.00% | C2 | yes |
| 4 | CMS1500 | `patient_dob` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C2 | yes |
| 5 | CMS1500 | `total_charge` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C3 | yes |
| 6 | UB04 | `patient_dob` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C2 | yes |
| 7 | UB04 | `patient_name` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C2 | yes |
| 8 | UB04 | `principal_diagnosis` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C1 | no |
| 9 | UB04 | `provider_npi` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C1 | no |
| 10 | UB04 | `type_of_bill` | 60 | 60 | 0 | 100.00% | 0.00% | 100.00% | C1 | no |
