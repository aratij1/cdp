# Existing 12-scan HITL diagnostic

21/21 extracted fields: {'NO_ACCEPTANCE_POLICY': 21}. All 12 documents required review. The recorded terminal reason is FIELD_POLICY_NOT_CONFIGURED: an acceptance-policy problem, not a measured recognition error. Critical consensus and validation cannot authorize acceptance without a configured field policy.

Governance is independently incomplete: claim boundaries and trusted labels are unavailable. Recognition correctness, source quality and complete-claim accuracy cannot be inferred from confidence or the HITL rate. No thresholds changed and no scans were opened.

The run receipt is COMPLETED, but only 9/12 document event chains recorded execution_complete; three routing holds produced no extracted fields. All 12 scans were attempted. Automatic outputs and runtime STP_SAFE were 0/12. Production STP_SAFE is NOT_EVALUABLE.
