# CDP Phase 4 — Authoritative Reference Matching

## Decision

**NEEDS_MORE_DATA.** The governed matching architecture now supports member, provider, ICD, CPT, HCPCS, and payer references. No authorized enterprise snapshot is configured, so the implementation cannot yet claim an accuracy, STP, or review-rate gain.

## Implemented

- Pluggable local snapshot, batch, REST, database, disabled, and test-fixture providers.
- Immutable local snapshots with version, timestamp, SHA-256 checksum, source identity, authorization, independent-truth declaration, and non-circular lineage declaration.
- Snapshot paths cannot escape their configured root, and checksum or connector failures become abstentions.
- Member matching uses exact member ID/DOB or DOB/name/address combinations. Fuzzy name alone cannot accept an identity.
- The field being corrected cannot verify itself. For example, correcting a member ID requires DOB, name, and ZIP evidence; correcting a patient name can use exact member ID and DOB without treating the erroneous name as an identity contradiction.
- Provider matching requires a valid exact NPI and active reference record. Existing NPI checksum validation remains mandatory.
- ICD/CPT/HCPCS matching requires an exact active code in a versioned, timestamped, checksummed snapshot.
- Payer matching requires exact payer ID; payer name is supporting evidence and is insufficient alone.
- Multiple records, contradictions, unauthorized providers, unknown/circular lineage, missing versions, inactive records, and provider errors all fail closed.
- Corrections preserve `raw_value`, `normalized_value`, `reference_candidate`, `corrected_value`, and `final_value`, plus source, version, matching/conflicting attributes, confidence, and the complete decision record.

## Safety observations

Test fixtures are always training-only and cannot become evaluation-eligible reference truth. Evaluation ground truth is not a runtime provider. Critical approved-correction workflows retain their distinct second-approver requirement, while independent authoritative references are approved by the policy engine only after the configured multi-attribute gates pass.

## Results

- Focused and architecture tests: 38 passed.
- Full regression suite: 572 passed, 5 skipped, and the one previously known frozen-manifest hash failure.
- Static checks: passed.
- Production reference snapshots enabled: 0.
- Safe review reduction: 0 / 262 = 0%.
- Review cases removed: 0.
- False accepts introduced: 0.
- Added cloud cost: $0.
- Accuracy and review-rate deltas: 0 percentage points because the capability has not been applied to development predictions without an authorized source.

## Limitations and next gate

- Enterprise eligibility, provider-directory, payer, and licensed code-set snapshots must be supplied and approved before measuring impact.
- Snapshot licensing and update cadence remain operator responsibilities.
- Provider name/address/taxonomy are recorded as supporting attributes; exact NPI remains the identity anchor.
- External-provider latency and cost cannot be estimated from local fixtures.

The next ordered phase is field-specific evidence policy. Reference-based acceptance must remain disabled for a domain until its source authorization, lineage, version, checksum, and match policy are all verified.
