# CDP Critical Acceptance Audit

The Phase 8.8C unchanged A/B/C replay auto-accepted **zero C2/C3 fields**. Therefore
the mandatory accepted-critical-field audit contains zero rows and there were zero
critical false accepts. The machine-readable audit is generated at
`evaluation_results/phase8_8c/critical_acceptance_audit.json`.

This is a safety recovery, not a coverage success. Critical candidates were withheld
because the historical replay lacks candidate provenance and field-specific structural
lineage. The canonical audit schema records, when a critical field is accepted:
truth and selected value, all candidate values/provenance, dependency matrix, E2
subtype, field E3, E4 strength, references, cross-field evidence, policy path,
correctness, false-accept status, and reason codes.

Adversarial tests prove that same-crop wrong-but-valid member IDs, currency amounts,
checksum-valid NPIs, and names cannot be accepted from OCR agreement plus plausibility.
An authorized reference contradiction remains a terminal review condition.
