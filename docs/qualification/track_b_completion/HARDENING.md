# Track-B control-plane hardening

Base control commit: `6e39d2c2ccc26ac26a351e5fd07530abe5d3965e`.
Frozen candidate: `2a310ed51720b854cca99d361940eb929027e529`.

Missing or invalid reviewer YAML now disables authority everywhere. Consumers require the current valid contract and its exact cached projection/hash. Session write authority binds both the contract and the operator-provisioned access code; removal, expiry, rotation or hash changes revoke writes. Stored observations are preserved. Truth cannot freeze through a stale cache.

The existing controller now uses `evaluation.track_b_jobs.advance` for serialized, durable attempts while preserving the frozen runtime job module. PID creation time and host identity prevent PID-reuse mistakes. A definitely dead executor without a receipt produces a retained failure record; retries require the identical request, configuration, deployment and executable hashes and cannot exceed max_attempts (default 1, maximum 5). Unknown launch state does not authorize retry. Valid receipts take precedence over all markers. Concurrent refreshes cannot create duplicate submissions.

Deployment activation requires contract and attestation validation before connectivity. All five jobs, executor hashes, service identity, pinned candidate, pipeline hash, ingestion/tenant/authorization fields, and UB canaries are checked. Kafka probing uses the deployment-owned, hash-pinned broker_probe executable with its configured security environment. No TLS/SASL/mTLS/OAuth configuration is weakened or replaced with plaintext. Reports suppress probe output and driver exceptions.

EXACT membership additionally requires a private approval receipt from the expected source owner, bound to the exact current CSV bytes, role, policy, approval reference and timezone-valid timestamp. Existing lineage, source hash, document grouping, complete claim, package and Track A isolation checks remain in force.

## Validation

| Check | Result |
|---|---|
| Focused control-plane/UI/membership/recovery tests | 94 passed |
| Full regression | 2,168 passed; 6 skipped; 2 warnings |
| Ruff / scoped mypy (9 files; Linux and Windows) | PASS |
| Architecture / git diff --check | PASS |
| Frozen runtime hashes | 641/641 unchanged |
| Sealed Track A artifacts | 498/498 unchanged |
| New semantic regressions detected | 0 |

`hardening_validation.json` binds the validation to the code and test-log hashes. Local tests use synthetic contracts and processes; they are not target-host operational qualification evidence. No metric, comparator, threshold or Track A runtime file changed.

The existing quality workflow now triggers on `closure/cdp-target` and runs control-plane lint/types plus an explicit Track-B synthetic unit/architecture selection and the existing integration, governance and UI jobs. The full regression result above is local; the full unit suite needs private historical artifacts unavailable on GitHub runners and remains configured for other branches. External production-evidence collection and historical Track A replay do not run on this hardening branch. No CI deployment credentials were invented.

## Current production qualification

**EXTERNAL_INPUT_REQUIRED**. The live final qualification report separates reviewer contract, deployment contract, connectivity, executor and owner-approval states. Empty contracts remain invalid/unconfigured; no reviewer identities, approvals, claims, hosts, credentials, prices or real qualification evidence were generated.

Remaining external inputs are the completed owner CSV and its approval receipt; independently verified reviewer/adjudicator assignments and runtime access codes; actual source-only reviews/adjudications; a designated deployment with attestation, job/probe executables and secured access; and approved pricing/provider configuration.

Next action: Ashish Singh completes the existing 150-page membership CSV for owner approval.
