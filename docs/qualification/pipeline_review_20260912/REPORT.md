# Pipeline review and fresh diagnostic ? 2026-09-12

**The pipeline is not production-ready.** Reproduced completion, acceptance-accounting, and delivery defects were fixed. Fresh end-to-end inference on all 30 existing engineering documents still gives **1/124 (0.81%) diagnostic field accuracy** and **1/86 (1.16%) critical-field accuracy**. The same-cohort baseline gives the same accuracy; no recognition improvement is claimed.

## What was measured

The measured inference commit is `84da61383a52e391e5d39f9ed3f779ba99ed2dcf`. All 30 documents were rerun with fresh SQLite, fresh object storage, a new OCR process, and empty OCR caches. Existing source seals and Track B isolation passed before inference. Reference values were not provided to inference. The reference and cohort digests were sealed before execution and checked again before scoring.

These are existing fixed-width engineering references, not independent source-reading labels or frozen Track B truth. Of 240 reference slots, 124 are comparable, 72 are not comparable, 30 have no reference, and 14 are ambiguous. Unavailable and ambiguous references are excluded explicitly. Missing extracted values on comparable fields remain failures in the denominator. No candidate Recall@5 is used as accuracy. No new real scans were labeled or claimed independently reviewed.

| Diagnostic metric | Result |
| --- | --- |
| Raw header-field accuracy | 1/124 ? 0.81% |
| Critical-field accuracy | 1/86 ? 1.16% |
| Automatically accepted fields | 0 |
| Accepted precision | NOT_EVALUABLE ? denominator 0 |
| Critical accepted precision | NOT_EVALUABLE ? denominator 0 |
| Extracted-field HITL | 62/62 ? 100% |
| Full comparable-field HITL | NOT_EVALUABLE; 16 observed routed, 108 routing states unknown |
| Comparable-field HITL bounds | 12.90%?100%; not an exact rate |
| Engineering claim HITL | 30/30 ? 100% |
| Runtime-declared safe STP / automatic outputs | 0/30 |
| Observed false / critical false accepts | 0 / 0; no automatic accepts |
| Production-qualified STP_SAFE | NOT_EVALUABLE |
| Total wall time | 633.14 seconds |
| Per-document P50 / P95 / P99 | 16.78 / 58.25 / 66.92 seconds |
| Throughput to terminal observation | 2.84 documents/minute |
| OCR requests / cache hits | 142 / 0 |
| Measured monetary cost | NOT_EVALUABLE |

Thirty documents were attempted. Twenty-nine emitted canonical validation decisions; one seven-page document stopped at routing review with `NO_AUTOMATED_EXTRACTION_ROUTE`. There were no captured worker exceptions. Eight documents had no extracted fields, including that routing hold. The shell nevertheless reported exit code 1 after the completion marker and receipt; this is retained as an execution-environment caveat rather than described as a clean process exit.

## Root causes established by review

1. **Runtime routing contracts are incompatible by default.** `Settings.enable_router_v3` defaults to false. Legacy nominations can omit `route_decision`, while the standard verifier requires canonical identity/layout evidence. This sends nominated forms to generic extraction. `diagnostic_metrics.json` records the actual nominations and verification outcomes. The frozen V3 configuration explicitly marks the router evaluation-only; this review did not silently promote it or weaken verification.
2. **Generic extraction lacks governed acceptance policies.** Every extracted field in the rerun required review with `FIELD_POLICY_NOT_CONFIGURED`. Unsupported schemas cannot be made production-ready by relabeling them CMS1500/UB04 or enabling acceptance without authority.
3. **Extraction coverage is poor under this route.** On the 124 comparable reference slots, 108 extracted candidates were missing and 15 were wrong. One matched reference field still required validation/review. These are diagnostic comparisons, not proof that all mismatches are OCR recognition errors.
4. **Zero-field validation was silent.** It changed document status and returned without a canonical completion outbox event. The revised path emits a durable review decision and output hold; duplicate validation and output deliveries remain idempotent in the regression.
5. **Candidate datatype evidence was incorrectly shared.** The best candidate's validity was applied to all alternatives. Each candidate now gets its own datatype result.
6. **Claim and scorecard STP paths were inconsistent.** An unsupported family could pass with an empty required-field denominator; HUMAN_CONFIRMED fields could qualify as STP_SAFE; post-HITL true-STP accounting could omit raw/final correctness. These paths are corrected and covered by adversarial tests.
7. **Service-line amounts were fabricated from claim totals.** Validation and output built a service line or inserted its charge from the printed claim total. Both fallbacks were removed; actual service-line evidence is preserved.
8. **Failed Kafka handlers could be acknowledged.** All eight live consumer loops swallowed handler exceptions and resumed the generator, allowing the Kafka adapter to commit. They now propagate failure, leaving the message uncommitted for supervised recovery. Synthetic tests use the real Kafka adapter with a fake broker and cover success and failure for every loop.
9. **Evaluation execution needed stronger binding.** It now checks the exact sealed cohort and source-hash set, binds resumed output to the candidate/cohort, and audits routing OCR. Missing source-closure files now produce `SOURCE_CLOSURE_INPUTS_REQUIRED` rather than a NoneType crash.

The live-delivery fix was applied after the frozen diagnostic completed. `delivery_fix_scope.json` proves that the ASTs of all eight `handle_one` methods were unchanged by that follow-up; only exception handling in `run_forever` changed. The diagnostic validates the direct worker handlers. Live broker behavior is covered by the synthetic delivery test, not by the local OCR run.

## Performance limits

Routing took 193.66 seconds; unstructured extraction took 397.29 seconds; preparation took 30.30 seconds. No standard-extraction worker ran. All 142 OCR requests were cache misses. No caching speedup or cross-worker token-reuse benefit is claimed. The maximum observed process RSS was approximately 7.43 GiB; CPU timing excludes child OCR-process CPU. Per-stage timing and library versions are in the aggregate JSON. Real service transport, cost, GPU execution, and cold-versus-three-warm output/evidence parity remain unqualified.

## Remaining release blockers

- Resolve the deployment's routing contract through the existing governed promotion process. The default legacy/evidence mismatch remains; enabling an evaluation-only router is not an authorized production qualification.
- Define and approve semantic and acceptance policies for supported document families. Owner-approved membership, independent reviewers/adjudication, and immutable Track B truth are still missing.
- Restore legitimate private test inputs outside Git or migrate historical replay tests to safe fixtures. Do not reintroduce sensitive documents to make tests pass. A frozen-router baseline hash mismatch also remains.
- Qualify restart/redelivery on actual deployment infrastructure. Preparation, routing, and extraction still need end-to-end duplicate-delivery validation; the consumer failure fix alone is not an exactly-once guarantee.
- Complete semantic-policy parity and output acceptance qualification. The permissive standalone SAME inference helper has no live-worker call sites found; the live reference-enrichment path rejects unapproved SAME. That distinction does not establish full semantic qualification.
- Clean the other exposed remote branches and enforce the required safety check through repository administration.

Recognition tuning, threshold changes, Track B execution, approvals, and reviewer identities were not manufactured. The next production step requires actual owner/reviewer inputs and an approved deployment/routing configuration. The measured low accuracy is preserved.


## Validation

Final full unit suite: **2,087 passed, 69 failed, 20 skipped**. Architecture plus integration: **43 passed, 6 skipped**. The focused pipeline suite before the delivery-only follow-up passed 127 tests with 6 skips; all 16 Kafka delivery regressions pass after that fix. The failure inventory is in `validation.json` and contains test identifiers/categories only.

Ruff passes for all changed files. Mypy passes for the seven core changed modules, but expanding to all twelve touched modules reports 63 errors in the pre-existing page-detection, standard-extraction, and retry type contracts. That expanded check remains FAIL. Full-repository Ruff was not rerun; the previous 344-finding result has not been cleared. Git whitespace, staged sensitive-asset, and feature HEAD-history checks pass. These results do not authorize merge or production release.
