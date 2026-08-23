# Phase 7A.12 Source Attestation

No source has been attested or inferred. Qualified intake requires an explicit `SourceLineageAttestation` containing source origin, acquisition method, template and renderer lineage, declared relationships, an independence rationale, usage and PHI status, reviewer and timestamp, an exact source hash manifest, authorization reference, and `PASS | PARTIAL | FAIL` status.

Only `PASS` sources with approved PHI and usage status can contribute to LOSO. Renderer variants, seeds, scans, crops, compressions, degradations, and copies from the same base/template lineage remain one source. The workflow recomputes each source hash manifest and rejects mismatches.
