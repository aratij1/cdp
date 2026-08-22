# CDP Field Blocking Matrix

> Required, critical, and claim-blocking are separate policy dimensions. No field blocks STP merely because it is critical.

| Family | Field | Required | Criticality | Blocks STP | Review when unresolved | Business impact | Identity | Financial | Clinical | Compliance | Downstream consumers |
|---|---|---:|---|---:|---:|---|---|---|---|---|---|
| CMS1500 | `insured_id_number` | yes | C3 | yes | yes | member eligibility and claim routing | high | high | low | low | eligibility, payer_routing, claim_submission |
| CMS1500 | `patient_addr2` | no | C0 | no | no | optional address detail | low | low | low | low | claim_submission |
| CMS1500 | `patient_dob` | yes | C2 | yes | yes | patient identity and eligibility | high | low | low | low | eligibility, member_matching, claim_submission |
| CMS1500 | `patient_name` | yes | C2 | yes | yes | patient identity | high | low | low | low | member_matching, claim_submission |
| CMS1500 | `total_charge` | yes | C3 | yes | yes | claim financial total | low | high | low | medium | financial_reconciliation, claim_submission |
| UB04 | `federal_tax_no` | yes | C2 | yes | yes | provider tax identity | low | medium | low | high | provider_validation, tax_reporting, claim_submission |
| UB04 | `patient_addr2` | no | C0 | no | no | optional address detail | low | low | low | low | claim_submission |
| UB04 | `patient_dob` | yes | C2 | yes | yes | patient identity and eligibility | high | low | low | low | eligibility, member_matching, claim_submission |
| UB04 | `patient_name` | yes | C2 | yes | yes | patient identity | high | low | low | low | member_matching, claim_submission |
| UB04 | `principal_diagnosis` | yes | C2 | yes | yes | medical necessity and adjudication | low | medium | high | high | medical_necessity, adjudication, claim_submission |
| UB04 | `provider_npi` | yes | C3 | yes | yes | provider identity and payment | low | high | low | high | provider_validation, payment, claim_submission |
| UB04 | `type_of_bill` | yes | C2 | yes | yes | institutional claim routing | low | medium | low | medium | institutional_routing, adjudication, claim_submission |

## Governance

`patient_addr2` is the explicit non-blocking example: it may remain unresolved without forcing review. All other listed blocking choices reflect current submission, identity, financial, clinical, or compliance dependencies; they were not changed merely to increase STP.
