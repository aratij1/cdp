# CDP Phase 8.5 Final Report

## Outcome

**NO PROMOTION; SAFE HITL remains active.** Phase 8.4 was reproduced exactly. Safety remains 100% accepted precision, zero false accepts, and zero critical false accepts. Claim STP remains 0% because no legitimate new evidence exists in this corpus.

## Frozen accuracy

- CMS: 95.09%
- UB: 96.50%
- Critical: 95.87%
- Safe field coverage: 66.21%
- Field HITL: 33.79%
- Claim HITL/STP: 100%/0%

## Dominant blockers

1. UB04.federal_tax_no: 50 claims; 50 single-blocker; unlock value 50.00.
2. CMS1500.member_id: 50 claims; 0 single-blocker; unlock value 12.28.
3. CMS1500.total_charge: 50 claims; 0 single-blocker; unlock value 12.28.
4. CMS1500.provider_npi: 50 claims; 0 single-blocker; unlock value 12.28.
5. CMS1500.patient_name: 44 claims; 0 single-blocker; unlock value 10.37.

## Decision rationale

The UB tax-number capability is production-shaped but unbenchmarked because the engineering pack omits the field. CMS member ID, NPI, and total blockers lack the independent evidence required by policy. Reducing blockers or manufacturing E5/E6 would violate the safety contract.
