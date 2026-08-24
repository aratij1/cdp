# Phase 8.10B runtime/evaluation parity

The canonical runtime and non-historical evaluation paths both load `cdp-runtime-decision@phase8.10b-v1` through `DecisionServiceFactory`. They therefore use the same runtime evidence policy, production route registry, `runtime` route mode, field policy, criticality policy, claim policy, and reference configuration.

| Gate | Result |
|---|---|
| Candidate generation parity | PASS |
| Policy identity parity | PASS |
| Route identity parity | PASS |
| Field decision parity | PASS |
| Claim decision parity | PASS |
| End-to-end parity | PASS |

The historical Phase 8.10 profile remains reproducible as `HISTORICAL_ONLY`; it uses the balanced policy and evaluation route mode and cannot claim runtime parity. Historical extraction metrics remain the frozen 89.05% overall, 88.74% CMS1500, 89.42% UB04, and 91.67% critical accuracy. Extraction behavior was not tuned during the parity fix.

The canonical runtime decision replay is materially different from the historical evaluation: field HITL is 95.83%, claim HITL is 100%, and claim STP is 0%. Accepted precision is 96.00% (24/25), with one critical false accept (`SB-CMS-010 diagnosis`: truth `Z30.0`, selected `Z30.0 .50`). This is exposed as a pre-existing runtime-policy safety defect, not hidden or tuned away in the parity phase. The machine-readable hashes and exact parity projections are in `evaluation_results/phase8_10b/parity_manifest.json`; canonical evidence results are in `correct_reviewed_summary.json`.
