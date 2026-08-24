# CDP Phase 8.7 Golden V3 Validity

Golden V3 is PHI-free engineering validation data, not production data, a production holdout, or production authority.

- `UB04.claim_total_consistency`: 50 observations; 50 valid; 0 invalid; 0 not independently verifiable; `decimal-sum-reconciliation-v1`
- `cpt_hcpcs`: 50 observations; 50 valid; 0 invalid; 0 not independently verifiable; `hcpcs-syntax-v1`
- `diagnosis`: 50 observations; 50 valid; 0 invalid; 0 not independently verifiable; `icd-syntax-v1`
- `federal_tax_no`: 50 observations; 50 valid; 0 invalid; 0 not independently verifiable; `tax-id-syntax-v1`
- `insured_name`: 50 observations; 0 valid; 0 invalid; 50 not independently verifiable; `none`
- `member_id`: 100 observations; 100 valid; 0 invalid; 0 not independently verifiable; `member-id-syntax-v1`
- `patient_dob`: 100 observations; 100 valid; 0 invalid; 0 not independently verifiable; `datetime-strptime-v1`
- `patient_name`: 100 observations; 0 valid; 0 invalid; 100 not independently verifiable; `none`
- `principal_diagnosis`: 50 observations; 50 valid; 0 invalid; 0 not independently verifiable; `icd-syntax-v1`
- `provider_name`: 100 observations; 0 valid; 0 invalid; 100 not independently verifiable; `none`
- `provider_npi`: 100 observations; 100 valid; 0 invalid; 0 not independently verifiable; `80840-prefix-luhn-v1`
- `relationship`: 50 observations; 0 valid; 0 invalid; 50 not independently verifiable; `none`
- `service_date`: 50 observations; 50 valid; 0 invalid; 0 not independently verifiable; `datetime-strptime-v1`
- `service_line.charge`: 146 observations; 146 valid; 0 invalid; 0 not independently verifiable; `decimal-currency-v1`
- `service_line.hcpcs`: 146 observations; 146 valid; 0 invalid; 0 not independently verifiable; `hcpcs-syntax-v1`
- `service_line.revenue_code`: 146 observations; 146 valid; 0 invalid; 0 not independently verifiable; `revenue-code-syntax-v1`
- `service_line.service_date`: 146 observations; 146 valid; 0 invalid; 0 not independently verifiable; `datetime-strptime-v1`
- `service_line.units`: 146 observations; 146 valid; 0 invalid; 0 not independently verifiable; `units-syntax-v1`
- `total_charge`: 100 observations; 100 valid; 0 invalid; 0 not independently verifiable; `decimal-currency-v1`
- `type_of_bill`: 50 observations; 50 valid; 0 invalid; 0 not independently verifiable; `type-of-bill-v1`
