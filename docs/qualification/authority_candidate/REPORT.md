# Candidate freeze, semantic authority, and saved-output diagnosis

## Immutable candidate binding

The new [candidate freeze](../candidates/1a857337c200f704a159f43a8acc6c00a8d184d3.json) binds exact Git commit `1a857337c200f704a159f43a8acc6c00a8d184d3` to 633 runtime components. It includes the runtime profile and seven configuration hashes (field, evidence, OCR routes, criticality, claim, reference, calibration), semantic-authority policy hash, and the acceptance/STP implementation manifest and hash. Hashes come from committed Git bytes with canonical line endings. The pipeline configuration digest covers the runtime component manifest. Creation is immutable and idempotent; verification reconstructs the record from Git and detects modified or added runtime files.

The historical Track A freeze remains byte-for-byte unchanged. The controller reports it as historical, separately from the qualification candidate. Execution preparation requires a valid candidate freeze and matching runtime, and retains the historical artifact seal check.

**Freeze integrity passes, but the authority changes in this revision are newer than 1a85733.** The controller therefore reports `RUNTIME_DRIFT`, with changed component paths. This is intentional: this new implementation requires its own selected, validated candidate SHA and a subsequent immutable freeze before qualification. Neither the historical freeze nor the 1a85733 freeze approves later code.

## Runtime authority

One resolver emits `AUTHORITY_VERIFIED`, `AUTHORITY_FORM_IDENTITY_REQUIRED`, `AUTHORITY_MEMBERSHIP_REQUIRED`, `AUTHORITY_REFERENCE_REQUIRED`, or `AUTHORITY_AMBIGUOUS`, plus all applicable blockers and the semantic policy hash. Verification requires scoped form evidence, complete owner-governed membership, matching claim/document/page ownership, and authorized reference provenance and candidate agreement when policy requires a reference. Conflicting references, attachments, missing source semantics, derived values, and unresolved SAME cannot verify authority. These inputs are internal governed runtime evidence contracts; the resolver does not create or independently approve their receipts.

Runtime automatic acceptance fails closed when authority is unresolved. This applies to preserved machine decisions on revalidation as well. Human-confirmed corrections remain human-confirmed and never become STP evidence. Authority context survives the retry event boundary. Review-only field policies remain review-only even if authority becomes available; this change does not approve new automatic routes or change thresholds. The resolver's result is distinct from deterministic validation and independent confirmation.

## Same 12 scans, unchanged saved OCR

| Diagnostic | Fields |
| --- | ---: |
| Extracted | 21 |
| Auto-eligible | 0 |
| HITL required | 21 |
| Missing field policy | 0 |
| Form identity required | 21 |
| Claim membership required | 21 |
| Reference authority required | 13 |
| Independent confirmation required | 19 |
| Deterministic validation blocked | 15 |

All 21 primary authority states are `AUTHORITY_FORM_IDENTITY_REQUIRED`; multiple missing stages are also reported. Absent scoped evidence in saved metadata is not proof that the source document itself is invalid.

| Validation blocker category | Fields |
| --- | ---: |
| FORMAT | 10 |
| CHECKSUM | 4 |
| DATE | 1 |
| CODE SET | 0 |
| CROSS-FIELD CONSISTENCY | 0 |
| TOTAL RECONCILIATION | 0 |
| MISSING REQUIRED VALUE | 0 |
| FORM IDENTITY | 0 |
| REFERENCE LOOKUP | 0 |
| OTHER | 0 |

The format failures include three ICD syntax failures, three tax-identifier format failures, one member-identifier format failure, two currency-format failures, and one label-contamination failure. Syntax is not code-set validation. These 15 failures are value-level deterministic failures, not authority/reference lookup failures; all still have separate authority blockers. They do not prove OCR recognition errors, field-label correctness, or actual clinical/code validity. Zero in a category means no such failure was reported, not that the corresponding check was performed and passed.

OCR calls were zero, models were unchanged, and saved execution bytes were unchanged (SHA-256 `096392c26a331bef9bbb2594b34da373352db28246c08092a4a91bbfbb859194`). No values or images are published. [Replay aggregates](disposition_replay.json) are bound to the implementation manifest in [validation receipt](validation_receipt.json). Accuracy, accepted precision, false accepts, claim HITL, and production `STP_SAFE` remain unmeasured. No OCR tuning was performed.

## Deployment and external inputs

The deployment draft now binds the requested candidate SHA and its pipeline digest. Preflight checks the exact candidate and computed pipeline binding, and returns `INVALID_CONTRACT` without network probes when prerequisites are missing. [Preflight details](deployment_preflight.json) list checks without credentials or connection values. The operator still must supply the governed host/environment, deployment ID and approval, ingestion endpoint, tenant and authorization environment, service settings, executable paths/hashes, secure broker probe, canary fingerprints, and deployment attestation. Known fields were configured; approvals and environment details were not invented.

Owner membership remains 0/150 confirmed; owner approval and membership are missing, reviewer registration is invalid, independent reviews and adjudications are zero, and truth is not frozen. [Read-only readiness](track_b_readiness.json) verifies governed input bytes were unchanged. No qualification jobs or production executions were launched.

The next execution gate is a selected freeze matching the authority implementation, then valid operator inputs and deployment preflight, independent dual review, adjudication, and frozen Track B truth. Engineering regression results do not constitute production qualification.
