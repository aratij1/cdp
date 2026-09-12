# Repository remediation status

Source: feature/claims-cdp-improvements, downloaded at 9c924e9.
Local checkout: cdp-safety-remediation. Existing workspace edits were not modified.

## Safety

The local history inventory flags raw claims, generated evaluation exports, TIFF/PDF document assets and archives. Flagged paths are removed from every ref in the isolated clone, not merely ignored in the working tree. Original GitHub history remains a separate publication/admin action. Remote pull-request refs, tags, forks, clones, cached views and artifact storage require repository-owner review; a branch rewrite alone does not certify their removal.

The repository-safety CI job scans the Git index and all fetched history on every push and pull request. It blocks private data paths, document extensions, TIFF/PDF/ZIP signatures even after renaming, and selected identifying fields in data exports. Output contains hashes and reason codes only. This is a conservative screening guard, not proof that arbitrary text, images or encoded payloads contain no PHI. Owners must classify potentially exposed originals privately. Do not upload source scans to CI or include their values in reports.

Require repository-safety / sensitive-assets in repository rules. GitHub administration permission is needed to enforce required checks; a workflow alone cannot prevent a direct push or a privileged bypass. Existing private-data-dependent replay checks must remain blocked until external governed inputs are provisioned.

## Track B and production acceptance

Reuse evaluation.qualification_closure and track_b_completion/INPUT_CONTRACT.md. Owner membership, reviewer identities, independent dual reviews, independent adjudication, frozen truth and actual pinned-candidate execution remain required. No reviewer decisions or approvals were fabricated. Track A is not a source of production truth.

Raw reporting includes field accuracy, critical-field accuracy, accepted precision, critical accepted precision, field HITL, claim HITL, STP_SAFE and all/critical false accepts. Denominators come from complete governed truth. Zero accepted fields gives undefined precision. STP_SAFE additionally verifies all claim fields accepted and correct against frozen truth, with no human intervention; declared STP remains diagnostic. Production STP gates now consume STP_SAFE. This changes the qualification contract, so prior seals and reports do not qualify the amended candidate.

current_acceptance_gate no longer fabricates zero false accepts or authorizes tuning from candidate coverage. Candidate Recall@5 and coverage remain engineering diagnostics.

Document semantic requirements are explicit in DOCUMENT_SEMANTIC_AUTHORITY.md. Binding them to the frozen comparator and verifying runtime policy parity remain prerequisites for qualification.

## OCR and performance

Identical concurrent OCR requests now share one computation per cache key. Backend failure permits retry. The routing worker now uses the existing versioned content cache and audit sink. Unstructured extraction already reuses page_lines across document family routing and layout extraction. Tesseract routing and Paddle extraction are different engines; their outputs are not interchangeable cached evidence.

The reported 404-second extraction and 218-second routing stages have not been reproduced on an authorized production workload. No speedup is claimed. Profile cold and warm full-path runs with engine/model/preprocessing versions pinned; collect routing wall time and OCR audit request/hit/miss/latency records, CPU and memory, then compare exact output/evidence parity. Cross-worker token reuse and bounded page parallelism still require backend thread-safety and tenant-isolation validation.

The six recognition failures remain deferred until independent truth and acceptance qualification are available. Do not tune against held-out Track B.

## Remaining external work

- Review sensitivity of exposed originals privately and complete GitHub history/cache/artifact cleanup.
- Require the safety check using repository administration.
- Supply actual owner/reviewer/adjudication records and freeze independent truth.
- Execute the amended candidate on the qualified production path; publish measured aggregate results.
- Verify semantic policy enforcement and profile the slow stages before further optimization.

Merge readiness: BLOCKED. Generalization and production accuracy: NOT QUALIFIED.
