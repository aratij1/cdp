# CDP Phase 8.4 Evidence Availability Matrix

This matrix describes enabled production evidence routes and Profile C replay outcomes. `No` means the class is not currently available from an enabled route for that field; it does not mean the evidence class is architecturally prohibited. E8 remains the terminal human path for every field.

| Family.field | E1 | E2 | E3 | E4 | E5 | E6 | E7 | Route lifecycle | Policy combinations | Reachability | Blocks STP | Reviews | Claim blockers |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|
| CMS1500.cpt_hcpcs | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 | REACHABLE | Yes | 0 | 0 |
| CMS1500.diagnosis | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 7 | 7 |
| CMS1500.insured_id_number | No | Yes | Yes | Yes | No | No | No | Production-approved E2 | E2+E3+E4 / E1+E3+E5 / E1+E3+E5+E6 / E1+E3+E4+E7 | REACHABLE | Yes | 0 | 0 |
| CMS1500.insured_name | Yes | No | Yes | Yes | No | Yes | No | Local | E1+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 1 | 1 |
| CMS1500.member_id | Yes | Yes | Yes | Yes | No | No | No | Alias to production-approved insured-ID E2 | E2+E3+E4 / E1+E3+E5 / E1+E3+E5+E6 / E1+E3+E4+E7 | REACHABLE | Yes | 50 | 50 |
| CMS1500.patient_dob | Yes | No | Yes | Yes | No | Yes | No | Local | E2+E3+E4 / E1+E3+E4+E6 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 1 | 1 |
| CMS1500.patient_name | Yes | No | Yes | Yes | No | Yes | No | Local | E2+E3+E4 / E1+E3+E4+E6 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 44 | 44 |
| CMS1500.provider_name | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 5 | 5 |
| CMS1500.provider_npi | Yes | No | Yes | Yes | No | Yes | No | Authorized reference required | E2+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REFERENCE_REQUIRED_EXPLICIT | Yes | 50 | 50 |
| CMS1500.relationship | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 0 | 0 |
| CMS1500.service_date | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 0 | 0 |
| CMS1500.total_charge | Yes | No | Yes | Yes | No | Yes | No | Local | E2+E3+E4 / E1+E3+E4+E6 / E1+E3+E4+E7 | REACHABLE | Yes | 50 | 50 |
| UB04.federal_tax_no | No | No | Yes | Yes | No | No | No | No extracted candidate | E2+E3+E4 / E1+E3+E5 / E1+E3+E4+E6 / E1+E3+E4+E7 | HUMAN_REQUIRED_EXPLICIT | Yes | 0 | 50 |
| UB04.member_id | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 | REACHABLE | Yes | 1 | 0 |
| UB04.patient_dob | Yes | No | Yes | Yes | No | Yes | No | Local | E2+E3+E4 / E1+E3+E4+E6 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 1 | 0 |
| UB04.patient_name | Yes | No | Yes | Yes | No | Yes | No | Local | E2+E3+E4 / E1+E3+E4+E6 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 50 | 0 |
| UB04.principal_diagnosis | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 | REACHABLE | Yes | 5 | 0 |
| UB04.provider_name | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REACHABLE | Yes | 4 | 0 |
| UB04.provider_npi | Yes | No | Yes | Yes | No | Yes | No | Authorized reference required | E2+E3+E4 / E1+E3+E5 / E1+E3+E4+E7 | REFERENCE_REQUIRED_EXPLICIT | Yes | 50 | 0 |
| UB04.total_charge | Yes | No | Yes | Yes | No | Yes | No | Local | E2+E3+E4 / E1+E3+E4+E6 / E1+E3+E4+E7 | REACHABLE | Yes | 1 | 0 |
| UB04.type_of_bill | Yes | No | Yes | Yes | No | No | No | Local | E1+E3+E4 | REACHABLE | Yes | 1 | 0 |

E8 human verification is available for every row. Profile C has 18 reachable rows, two explicit reference-required rows, one explicit human-required row, and zero unexpected unreachable policies. The apparent reachability of CMS member ID is prospective through its governed insured-ID alias route; the frozen replay contains no qualifying E2, so all 50 remain reviewed.
