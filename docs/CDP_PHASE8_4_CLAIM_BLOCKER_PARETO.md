# CDP Phase 8.4 Claim Blocker Pareto

## Outcome

Profile C preserves zero false accepts but all 100 claims still require HITL. UB claims have one explicit missing-field blocker; CMS claims have multiple unresolved fields that lack independent corroboration. Changing `blocks_stp` would hide these defects and was not done.

| Family | Field | Criticality | Claims blocked | Single blocker | Multi blocker | Correct but reviewed | Wrong and rejected | Dominant missing evidence |
|---|---|---:|---:|---:|---:|---:|---:|---|
| CMS1500 | member_id (alias of insured_id_number) | C3 | 50 | 0 | 50 | 50 | 0 | E2 on frozen replay |
| CMS1500 | provider_npi | C1 | 50 | 0 | 50 | 40 | 10 | E2; checksum E4 absent for 48 |
| CMS1500 | total_charge | C3 | 50 | 0 | 50 | 49 | 1 | E2; CMS line-total E6 unavailable |
| UB04 | federal_tax_no | C2 | 50 | 50 | 0 | 0 | 0 | Field decision absent; explicit human requirement |
| CMS1500 | patient_name | C2 | 44 | 0 | 44 | 42 | 2 | Independent identity corroboration |
| CMS1500 | diagnosis | C1 | 7 | 0 | 7 | 0 | 7 | E4 syntax failure |
| CMS1500 | provider_name | C1 | 5 | 0 | 5 | 0 | 5 | E4 token-boundary failure |
| CMS1500 | patient_dob | C2 | 1 | 0 | 1 | 0 | 1 | Missing value, therefore E4/E6 unavailable |
| CMS1500 | insured_name | C1 | 1 | 0 | 1 | 0 | 1 | Ambiguity/conflict |

## STP ceiling

UB `federal_tax_no` is required by explicit business policy but does not exist in the frozen extraction candidates. Consequently, even perfect resolution of every CMS blocker can produce at most 50% claim STP on this corpus. The requested 60% first frontier is therefore unreachable without either adding a governed UB tax-ID extraction decision or changing business policy. Both are outside the Phase 8.4 extraction freeze.

The next safe work is to qualify production-independent confirmation for CMS member ID and NPI, and to provide genuine CMS service-line/total reconciliation. Raw confidence threshold changes cannot resolve these blockers safely.
