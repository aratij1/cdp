# CDP Phase 8.6 Final Report

Phase 8.6 kept UB benchmark repair separate from CMS evidence acquisition. No policy threshold or blocking flag was weakened.

Combined safe coverage: **77.60%**; field HITL: **22.40%**; claim STP: **0.00%**; claim HITL: **100.00%**; false accepts: **0**; critical false accepts: **0**; cloud cost: **$0**.

Illustrative fully loaded cost is **$0.1479 per page** under the frozen Phase 8.3 labor and infrastructure assumptions. Remaining claim blockers: `provider_npi` (98), `patient_name` (94), `provider_name` (9), `diagnosis` (7), `member_id` (5), `principal_diagnosis` (5), `patient_dob` (2), `total_charge` (2), `insured_name` (1), `type_of_bill` (1). Claim STP remains disabled because those fields do not yet satisfy the unchanged evidence and validation policy.
