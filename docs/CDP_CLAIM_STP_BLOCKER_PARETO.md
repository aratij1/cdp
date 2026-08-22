# CDP Claim STP Blocker Pareto

> `EVIDENCE_FRONTIER_V2` synthetic evaluation only. Sorted by claim unlock value; evaluation-only routes are not runtime authority.

| Field | Family | Claims blocked | % non-STP | Single blocker | Multi blocker | Claim unlock value | Available evidence | Missing evidence | Current policy | Cheapest safe resolution | Production route status |
|---|---|---:|---:|---:|---:|---:|---|---|---|---|---|
| `patient_name` | UB04 | 18 | 75.00% | 3 | 15 | 3 | E1, E3, E4 | E2 | *.patient_name@evidence-policy-v2-candidate | `HUMAN_REVIEW` | `EVALUATION_ONLY` |
| `federal_tax_no` | UB04 | 17 | 70.83% | 2 | 15 | 2 | E1, E3, E4 | E2 | default.C2@evidence-policy-v2-candidate | `CROSS_FIELD_RECONCILIATION` | `EVALUATION_ONLY` |
| `patient_name` | CMS1500 | 3 | 12.50% | 2 | 1 | 2 | E1, E3 | E2, E4 | *.patient_name@evidence-policy-v2-candidate | `DETERMINISTIC_VALIDATION` | `EVALUATION_ONLY` |
| `insured_id_number` | CMS1500 | 1 | 4.17% | 1 | 0 | 1 | E1, E3, E4 | E2 | CMS1500.insured_id_number@evidence-policy-v2-candidate | `HUMAN_REVIEW` | `PRODUCTION_APPROVED` |
| `patient_dob` | UB04 | 15 | 62.50% | 0 | 15 | 0 | E1, E3, E4 | E2 | *.patient_dob@evidence-policy-v2-candidate | `HUMAN_REVIEW` | `EVALUATION_ONLY` |
| `type_of_bill` | UB04 | 15 | 62.50% | 0 | 15 | 0 | E1, E3, E4 | E2 | default.C2@evidence-policy-v2-candidate | `CROSS_FIELD_RECONCILIATION` | `EVALUATION_ONLY` |
| `principal_diagnosis` | UB04 | 15 | 62.50% | 0 | 15 | 0 | E1, E3, E4 | E2 | default.C2@evidence-policy-v2-candidate | `CROSS_FIELD_RECONCILIATION` | `EVALUATION_ONLY` |
| `total_charge` | CMS1500 | 1 | 4.17% | 0 | 1 | 0 | E1, E3, E4 | E2 | *.total_charge@evidence-policy-v2-candidate | `CROSS_FIELD_RECONCILIATION` | `EVALUATION_ONLY` |

## Interpretation

There are 24 non-STP claims. Claim unlock value counts only claims where resolving this field alone would make the claim STP-eligible; multi-blocker claims receive no speculative unlock credit.

No blocker was relabeled and no route was promoted by this analysis.
