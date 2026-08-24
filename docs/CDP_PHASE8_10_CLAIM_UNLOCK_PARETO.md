# CDP Phase 8.10 — Claim Unlock Pareto

Every evaluated claim remains multi-blocked; no field is a single blocker and
all measured claim-unlock values are zero. The highest blocked populations are:

| Field | Claims blocked | Correct but reviewed | Wrong extraction |
| --- | ---: | ---: | ---: |
| provider_name | 60 | 53 | 7 |
| provider_npi | 60 | 60 | 0 |
| total_charge | 60 | 53 | 7 |
| patient_name | 60 | 33 | 27 |
| patient_dob | 60 | 59 | 1 |
| member_id | 60 | 57 | 3 |
| type_of_bill | 30 | 26 | 4 |
| principal_diagnosis | 30 | 25 | 5 |
| federal_tax_no | 30 | 30 | 0 |
| insured_name | 30 | 16 | 14 |

Because claim coupling remains the limiting factor, improving a high-error field
alone is unlikely to create STP. Evidence acquisition should be evaluated as a
bundle that closes all blockers on a claim without correlated-evidence credit.

Artifact: `claim_unlock_pareto.json/csv`.
