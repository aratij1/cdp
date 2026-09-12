# Engineering measurement control plane

Runtime candidate `5c325326c5f83247680b18f4340eab2ce56a2963` remains unchanged and matches its immutable manifest. Runtime identity and control-plane identity are reported separately. Report-only/control-plane commits do not become new runtime candidates. A real Git test proves a new report commit changes the control-plane SHA while runtime matching remains PASS.

## Actual measurement status

The local source-only review and saved-OCR scoring workflow is implemented and tested with synthetic labels. **The real engineering measurement is not complete:** no external governed-state root or independent engineering reviewer has been supplied. No real source labels were created. Missing state is reported as unknown, never reset to zero.

| Requested output | Current result |
| --- | --- |
| Runtime candidate | 5c32532; PASS |
| Control plane | cd01417; runtime matched; WAITING_FOR_GOVERNED_STATE |
| Governed root | NOT_CONFIGURED; counters UNKNOWN_NOT_ZERO |
| Real engineering labels / 21 | UNKNOWN_STATE_NOT_MOUNTED / 21; none created in this task |
| Comparable fields | NOT_EVALUABLE |
| Exact engineering accuracy | NOT_EVALUABLE |
| Normalized engineering accuracy | NOT_EVALUABLE; no new normalization approved |
| Critical engineering accuracy | NOT_EVALUABLE |
| Recognition errors | NOT_EVALUABLE |
| Localization errors | NOT_EVALUABLE |
| Validator true / false rejects | NOT_EVALUABLE |
| HITL | 21/21 |
| OCR calls during this work | 0 |
| Saved OCR SHA before/after | 096392c26a331bef9bbb2594b34da373352db28246c08092a4a91bbfbb859194; unchanged |
| Track B | NOT_RUN; external state not mounted; prior counters are not overwritten |
| Production metrics | NOT_EVALUABLE |
| Validation | 2,185 unit tests passed (88 skipped); 43 architecture/integration passed (6 skipped); Ruff and governed mypy (46 modules) PASS |
| Commit | See the control-plane commit bound in validation_receipt.json |

See [diagnostic_report.json](diagnostic_report.json) for separate extraction-quality, automation, and production metrics. No source or prediction values appear in this report. A mismatch alone cannot distinguish recognition from localization. Those counts remain unattributed until causal evidence is supplied; they are not reported as zero. Validator false/true rejection requires a matching source label and an explicit source-validity judgment. Blank, not-present, unreadable, conflict, and not-applicable labels are excluded from value accuracy and counted separately. Exact accuracy uses the original raw OCR string. Critical accuracy uses the existing C2/C3 field policy. Normalization is not silently introduced.

## Why all 21 fields require HITL

The original saved decision metadata independently reports extraction, validation, authority, consensus requirement, acceptance, and disposition. It is not an accuracy label.

- All 21 have extracted values; correctness is unverified.
- 15 fail deterministic validation: FORMAT 10, CHECKSUM 4, DATE 1.
- 21 require form identity and membership authority; 13 also require reference authority.
- 19 require independent confirmation. This is an outstanding policy requirement, not a measured disagreement rate.
- All 21 have review-required acceptance policies and remain HITL-required.

Field-level stage rows are written only to private external engineering state once configured. Git reports contain stage aggregates. The question of how many of the 15 are recognition errors, localization errors, validator defects, or invalid printed values remains unanswered pending source labels and causal review.

## External governed state

Set `CDP_QUALIFICATION_STATE_ROOT` to an existing absolute private directory outside Git. There is no automatic fallback. `CDP_QUALIFICATION_ALLOW_LOCAL_STATE=1` is an explicit development-only compatibility option; tests select it explicitly. Production operators should leave it unset.

Existing logical inputs resolve to this stable mount across source clones:

| External folder | Logical artifacts |
| --- | --- |
| membership/ | owner CSV, membership approval, lineage, claim membership |
| reviewers/ | reviewer registry YAML, registry cache, reviewer authority status |
| reviews/ | blind review database, provenance database, source bindings, other review artifacts |
| adjudication/ | separate adjudication artifacts; existing adjudication tables remain in the review database |
| truth/ | frozen Track B truth and scored truth |
| deployment/ | deployment contract, attestation, pricing, jobs and receipts |
| engineering/fresh_12/ | engineering source manifest, labels, engineering truth, private diagnostics |

Reports identify the mount by a hashed root ID rather than its potentially sensitive path. Existing membership/registry hashes and review provenance contracts remain authoritative. Missing mounts fail closed, stale registry caches cannot authorize review, and frozen truth cannot be replaced. Engineering truth is explicitly rejected as production truth.

**Migration is pending authorization.** No existing scans, saved execution files, or governed inputs were copied. Automatic approval review rejected a proposed transfer to an unspecified external destination. The operator must provide the exact private directory and approve the sensitive payload. Until approved relocation occurs, the intake workflow references the original source files and requires their hashes to match; it does not pretend those source blobs have been durably relocated.

## Local source-only workflow after the mount and reviewer are supplied

1. Place existing governed state at the mapped private locations, retaining the original bytes and approval/provenance relationships. Do not fabricate missing memberships or reviews.
2. Prepare the engineering manifest with `python -m evaluation.engineering_review_intake --saved <existing-private-run-directory>`. Intake selects only opaque IDs, requested field names, page/frame bindings and source hashes. No OCR values, confidence, candidate strings, or predicted bounding boxes enter the review manifest. It requires exactly the existing 12 scans and 21 fields.
3. Configure a private `CDP_ENGINEERING_REVIEW_TOKEN` of at least 16 characters and run `python -m evaluation.engineering_review_app --reviewer-reference <assigned-reference>`. It binds to 127.0.0.1:8766, disables access logs, requires sign-in, and serves images only to the local authorized session. No remote OCR/model service is called.
4. Independently read each source; enter VALUE, BLANK, NOT_PRESENT, UNREADABLE, SOURCE_CONFLICT, or NOT_APPLICABLE. Enter a source region and source-only attestation. The form is blank; no prediction is prefilled. Review values, reviewer identity, timestamp, source hash and provenance stay private. Submitted labels are immutable; do not submit uncertain transcription as a confirmed value.
5. Freeze the completed 21-label engineering truth in the UI. Its scope is FRESH_12_ENGINEERING_ONLY and production_authority is false. No Track B labels or approvals are generated.
6. Run `python -m evaluation.engineering_diagnostic_report --saved <same-private-run-directory> --output <aggregate-report-path>`. It checks frozen truth, label/source provenance and the original OCR hash before comparison, then verifies the OCR hash again afterward. No OCR executes.

7. After source truth is frozen, an independent causal review can be recorded using `python -m evaluation.engineering_attribution --file <private-attribution-json> --reviewer-reference <assigned-reference>`. Each private row contains an opaque field_id, one allowed root_cause, and an evidence_reference. The importer binds the attribution to frozen truth and the saved OCR hash. It never updates source labels, and refuses to run before truth is frozen. Rerun the aggregate scorer to count confirmed recognition/localization errors; unattributed mismatches remain explicitly unknown.

Any causal review beyond exact comparison must establish recognition versus localization or normalization independently; do not infer those causes merely from validation failure. No new normalized comparator has been approved, so normalized accuracy stays explicitly unavailable.

## Recommendations without runtime tuning

AUTHORITY / FORM_IDENTITY / MEMBERSHIP: supply governed, scoped evidence. REFERENCE: supply authorized reference provenance. CONSENSUS: retain existing independent confirmation rules. VALIDATION / OCR_RECOGNITION / LOCALIZATION: complete source-only labels and causal review before proposing a change. None of these diagnostics authorizes tuning the frozen candidate.

Track B stays independent: owner membership, owner approval, valid independent reviewer registry, dual review, adjudication, frozen truth, valid deployment and preflight, then untouched candidate execution. Engineering labels never become Track B truth.
