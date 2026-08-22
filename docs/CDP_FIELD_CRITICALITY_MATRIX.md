# CDP Field Criticality Matrix

Policy version: `field-acceptance-v1`. The executable source is `config/field_acceptance_policies.yaml`.

| Field | Form | Criticality | Business impact | Financial | Identity | Compliance | Required | Blocks STP | Review unresolved | Reason |
|---|---|---|---|---|---|---|---:|---:|---:|---|
| `patient_name` | CMS-1500 | C2 | Patient identity | none | high | none | yes | yes | yes | A wrong value can attach the claim to the wrong person. |
| `patient_dob` | CMS-1500 | C2 | Identity and eligibility | none | high | none | yes | yes | yes | Required identity discriminator and eligibility input. |
| `insured_id_number` | CMS-1500 | C3 | Member eligibility and routing | high | high | none | yes | yes | yes | A wrong ID can route payment to the wrong coverage record. |
| `total_charge` | CMS-1500 | C3 | Submitted claim total | high | none | medium | yes | yes | yes | Directly controls the submitted amount. |
| `patient_addr2` | CMS-1500 | C0 | Optional address detail | low | low | low | no | no | no | Optional continuation data must not force claim review. |
| `patient_name` | UB-04 | C2 | Patient identity | none | high | none | yes | yes | yes | Required identity attribute. |
| `patient_dob` | UB-04 | C2 | Identity and eligibility | none | high | none | yes | yes | yes | Required identity discriminator. |
| `provider_npi` | UB-04 | C3 | Provider identity and payment | high | none | high | yes | yes | yes | Requires checksum-valid, independently supported provider identity. |
| `type_of_bill` | UB-04 | C2 | Institutional routing | medium | none | medium | yes | yes | yes | Controls claim classification and adjudication. |
| `principal_diagnosis` | UB-04 | C2 | Medical necessity and adjudication | medium | none | high | yes | yes | yes | Required diagnosis field with compliance impact. |
| `federal_tax_no` | UB-04 | C2 | Provider tax identity | medium | none | high | yes | yes | yes | Required provider tax identifier. |
| `patient_addr2` | UB-04 | C0 | Optional address detail | low | low | low | no | no | no | Optional continuation data must not force claim review. |

Unspecified fields fail to a C1, non-required but review-blocking default until a form owner approves an explicit policy. This avoids silently dropping unknown fields without classifying them as C2/C3 merely because they appear on a claim.
