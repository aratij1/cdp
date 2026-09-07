# CDP technical closure ? consolidated measured report

Final status: **MEASURED_TECHNICAL_CEILING**.

The retained local engineering stack reaches **91/118 candidate Recall@5 (77.12%)**, including **69/86 critical fields (80.23%)**. Source-based ranking reaches **74/118 Recall@1 (62.71%)**. The same 30 claims complete a fresh processing attempt with **zero execution failures**, but **zero STP_SAFE outputs**. Production qualification remains unavailable without independent Track B truth.

This status describes the measured limit of the bounded, available recognition and review-only strategies. Six source-visible recognition misses remain technical failures. Future model development and independently qualified integration can improve this result; neither their success nor production generalization has been established.

## Frozen scope and authority

Track A contains 30 exact owner-confirmed claims, 67 source pages, 118 comparable fields and 86 critical fields. No denominator changed. The 64/118 baseline and 48/86 critical baseline are preserved through 170 hash-bound input/output/implementation entries in [baseline64_manifest.json](technical_closure/baseline64_manifest.json), with private immutable snapshots. Source images, membership, references, OCR captures, topology registrations and candidate pools remain linked by hashes. The original baseline commit is `bf0ef3ce67b5aeea35ce6d9d9452a328d4d7a297`.

All new candidate and ranking work is **REVIEW_ONLY / ENGINEERING_ONLY**. Track A packages already have development exposure, so no clean validation or generalization claim is made. Acceptance policies and thresholds are unchanged. Track B images, predictions and annotations were not used for development. The fresh path reused the prior pixel-isolation receipt while checking sealed membership/source metadata.

## Candidate coverage and ranking

| Measure | Frozen baseline | Retained result | Target |
|---|---:|---:|---:|
| Candidate Recall@1 | 43/118, 36.44% | 74/118, 62.71% | Improve while preserving R@5 |
| Candidate Recall@3 | 57/118, 48.31% | 90/118, 76.27% | Diagnostic |
| Candidate Recall@5 | 64/118, 54.24% | 91/118, 77.12% | ?98% |
| Critical Recall@5 | 48/86, 55.81% | 69/86, 80.23% | ?99% |
| Claims with no comparable candidate misses | 7/30 | 13/30 | Coverage only |

Existing-token topology recovered 17 fields before additional OCR. Retained bounded recognition and observed-token assembly recovered 10 more. The shared `FormFieldTopology` contract separates CMS1500, UB04 and governed OTHER document types. It requires source hashes, reviewed geometry, field-role/label evidence and schema-constrained assembly. Historical experiment runners are retained for frozen reproduction; new work uses the consolidated runners and shared topology package.

The four statement totals were recovered only from reviewed claim-total locations: a laboratory summary row, a labeled receipt charge, and statement summary rows. The two documents without a printed claim-wide total remain unresolved and in the denominator. No line-charge sum, paid amount, noncovered amount, identity substitution or invented digits were used to fill them.

| Field family | Comparable | R@1 | R@5 |
|---|---:|---:|---:|
| Insured name | 26 | 14 | 16 |
| Member ID | 20 | 9 | 15 |
| Patient DOB | 6 | 6 | 6 |
| Patient name | 30 | 16 | 21 |
| Principal diagnosis | 6 | 6 | 6 |
| Total charge | 30 | 23 | 27 |
| Service date / provider name | 0 / 0 | ? | ? |

Ranking uses source provenance, region evidence, observed confidence and candidate completeness. It receives no reference value or similarity feature. It reorders within the existing top-five envelope, preserving the candidate multiset and Recall@5. Final correct ranks: rank 1 = 74, rank 2 = 12, rank 3 = 4, rank 4 = 1; absent = 27.

## Pollution and strategy retention

Thirty additional candidates produce 27 additional covered fields and three new reference-nonmatching alternatives. Mean candidates per field changes from 1.907 to 2.161; P95 remains 5; fields with more than five candidates remain 3; equivalent duplicates remain 0. Non-equivalent alternatives increase by 19 and new ambiguity blockers by 10. These costs remain visible in review rather than being treated as automatic acceptance.

The 34 bounded secondary calls consumed 68.379 seconds of measured inference, excluding model loading. Peak observed pilot RSS was 4.16 GiB. This includes five local Florence/GOT VLM calls and six dedicated handwritten TroCR calls; external LLM calls were zero. Startup failures before inference are excluded from call counts and retained in private logs.

Retained families: source-bound Rapid patient-name recovery, grid-cleaned charge/DOB evidence, detector-free printed name rows, corrected full-glyph diagnosis crops, the usable Florence name result, and handwritten TroCR total-charge recovery. All outputs in each retained family are subjected to the same source/schema/confidence gates. Family selection uses exposed engineering outcomes and does not confer release authority.

Rejected families include Rapid insured-name/ID recovery, grid diagnosis recovery, truncated diagnosis crops, detector-free charge recovery, GOT printed-name/charge recovery, Florence ID recovery, and TroCR names/IDs. Invalid or insufficient-evidence model outputs do not become candidates. Low-yield model expansion, truth-derived name repairs, source-absent total construction and threshold relaxation were not retained. The full utility formula and per-family gain, ambiguity, time, memory and decisions are in [strategy_ledger.json](technical_closure/strategy_ledger.json).

## Remaining causes and measured limits

Every remaining miss has one primary cause; UNKNOWN = 0.

| Primary cause | Fields |
|---|---:|
| OCR_RECOGNITION_FAILURE | 6 |
| SOURCE_SEMANTIC | 6 |
| REFERENCE_NOT_DIRECTLY_EXTRACTABLE | 7 |
| SOURCE_ILLEGIBLE | 2 |
| SOURCE_ABSENT | 6 |

The six recognition failures include five critical fields across four claims. Available bounded engines did not recover these fields safely. They are explicitly technical failures, not relabeled as source absence. The other 21 misses require source clarification, identity/relationship authority, improved legibility, or an approved reference-representation contract. Even recovery of all six recognition failures would yield at most **97/118 (82.20%) under the unchanged source/reference contract**; this is an upper bound, not a measured score.

Claim distance buckets 0/1/2/3/4+ improve from 7/7/5/7/4 to **13/10/4/3/0**. Four claims have remaining technical candidate blockers; fifteen have source/contract candidate blockers; seventeen have either, with overlap. Candidate completeness does not establish STP. Details and current opportunity ranking are in [consolidated_failure_inventory.json](technical_closure/consolidated_failure_inventory.json), [closure_opportunity_rank.json](technical_closure/closure_opportunity_rank.json) and [claim_blocker_accounting.json](technical_closure/claim_blocker_accounting.json).

## Field routing, acceptance and claim decision

All 118 comparable fields are accounted for. Historical canonical records contain 15 comparable fields routed to HITL and 103 comparable fields not emitted under their expected names. The 47 other persisted fields remain outside this frozen comparison contract and are preserved. Shadow pools contain 106 fields with candidates and 12 without candidates. No field was suppressed to improve review metrics.

An isolated review handoff creates or reuses all 118 comparable review slots, including empty review placeholders for missing fields. Empty placeholders carry full-page review context only, no asserted value localization. Candidate values are presented for review and are never automatically selected as canonical values. Engineering staged field review is **118/118 (100%)**; claim review is **30/30 (100%)**. These exceed the 10% and 20% targets.

Automatic accepts = 0. Accepted precision and critical accepted precision are **NOT_EVALUABLE_NO_ACCEPTS**, not 100%. Observed critical false accepts = 0 with no accepted denominator. Release accuracy, critical release accuracy and production STP remain unqualified. Canonical decisions in the simulated full-cohort revalidation are `STP_STANDARD`, not `STP_SAFE`; the output gate holds every claim. Generic canonical policy decisions and the additional engineering/source/authority blockers are reported separately rather than equating a generic decision with safe release.

## Output contract and actual review lifecycle

The output worker now records `output.review.required` and `NEEDS_REVIEW` atomically when a valid decision cannot safely serialize. The completion marker makes duplicate delivery idempotent. Governed unstructured documents remain in a generic review path. Unknown explicit form identities fail closed; neither CMS nor UB identity is invented. Standard-form serializers remain behind the STP_SAFE gate, with provenance/parity checks preserved.

On the unchanged historical 30-claim extraction, all 22 former output exceptions become explicit review holds, with zero output execution failures and zero safe outputs. The other eight claims remain review cases without a validation event. Focused tests and the regression suite cover standard output, rejected unsafe disposition, generic hold, unknown form rejection and restart idempotency.

The existing review API was exercised on isolated copies, first on 15 pre-existing eligible tasks and then on patient-name corrections for all 30 claims after complete review-slot handoff. The full run measured **30 corrections ? 30 HUMAN_CONFIRMED/PENDING states ? 30 transactional revalidation requests ? 30 canonical decisions ? 30 output review holds**. Corrected fields pending after revalidation = 0; unsafe outputs = 0; execution failures = 0. Duplicate task, validation and output deliveries were exercised. **Actual human reviews = 0.** Simulated engineering-reference corrections did not create trusted release truth or production authority.

See [output_contract_replay.json](technical_closure/output_contract_replay.json), [revalidation_lifecycle.json](technical_closure/revalidation_lifecycle.json), [candidate_handoff_lifecycle.json](technical_closure/candidate_handoff_lifecycle.json) and [routing_acceptance_scorecard.json](technical_closure/routing_acceptance_scorecard.json).

## Fresh full path and latency

A fresh run at architecture commit `92dfe676be20e5db33b8817af02024667cccb761` processed all 30 claims and 67 source pages through real production handlers with isolated SQLite, object storage and in-process transport. It reached extraction on 29 claims, produced 22 validation decisions and 22 output holds, and had **zero execution failures**. Canonical field values and dispositions equal the historical run. Safe outputs remain 0/30; the other claims remain in review.

Total claim processing was **663.781 seconds**, or **9.907 seconds per intake page**. Post-first-claim P95 was **27.022 seconds per source page**, calculated as each claim's complete processing time divided by its source-frame count. This is claim-amortized service latency. It does not measure individual page completion latency or production queue/network/storage delay, and later first use of an engine may still be cold. The earlier approximately 6.632-second page-path benchmark has a narrower scope and is not substituted for this result.

Dominant measured stages: unstructured extraction 404.412 s, routing 218.226 s, preparation 36.676 s. The installed ONNX runtime exposes Azure and CPU providers; the local Intel Arc GPU has no installed GPU execution provider. No rejected thread, resolution or concurrency sweeps were repeated. Status: **HOST_LATENCY_LIMIT_MEASURED**; production SLA is not qualified.

Target-host command, after installing the OCR runtime, setting `TESSERACT_CMD`, and mounting sealed inputs/source assets at their declared paths:

```powershell
python -m evaluation.technical_closure_downstream --fresh-output evaluation_results/technical_closure/target_host_fresh
```

The output directory must be new. A production-host run also needs deployment/transport/storage attestation and explicit warm-page SLA measurement. See [fresh_path_scorecard.json](technical_closure/fresh_path_scorecard.json) and [accelerator_availability.json](technical_closure/accelerator_availability.json).

## Cost

The fresh path records 75 Paddle OCR calls. Routing adds 67 Tesseract calls, reconstructed from the 67 prepared pages and the committed router's one-anchor-extraction-per-page control flow; this is distinguished from a separate runtime counter. Total primary calls are **142/67 = 2.119 per intake page**. All 62 retry events request human review, so fresh secondary OCR and external LLM calls are zero. The 34 closure pilot calls are reported separately.

Observed paid model-endpoint cost is $0/page for this local-only path. **Compute, authority lookup, storage/orchestration and total cost are NOT_CONFIGURED**. Authority lookup calls were not separately instrumented. Legacy YAML scenario assumptions are not verified prices for this workstation. Total cost is not reported as zero. See [measured_cost_scorecard.json](technical_closure/measured_cost_scorecard.json).

## Independent Track B and qualification

Metadata-only verification finds 150 bound source pages, zero established claim bindings, zero completed reviews, zero trusted labels, no configured reviewer registry and no release truth manifest. The source-view hash remains unchanged. Independent membership, authorized dual review/adjudication and a frozen truth manifest are still required before automatic final qualification can run.

Final production qualification is **NOT_EVALUABLE**, not PASS or FAIL. Track A is never substituted for Track B. No reviewer messages, fabricated labels or prediction-guided review were created. See [track_b_readiness.json](technical_closure/track_b_readiness.json).

## Verification, checkpoints and reproduction

Architecture checkpoint: `92dfe676` ? durable output review, shared shadow topology, event-bus protocol typing, isolated revalidation storage and safety tests. Consolidated evidence/runners are committed as the following logical checkpoint. Unrelated pre-existing UI and qualification-report edits remain outside these checkpoints.

The final validation receipt is [validation.json](technical_closure/validation.json). Private candidate values, claim images, model caches, databases, OCR outputs and correction records remain local. [artifact_seal.json](technical_closure/artifact_seal.json) binds the final evidence without publishing those values.

With the private frozen artifacts mounted, the consolidated commands are:

```powershell
python -m evaluation.technical_closure --consolidate
python -m evaluation.technical_closure --rank
python -m evaluation.technical_closure --routing
python -m evaluation.technical_closure_downstream --measure
```

Historical OCR recipes are preserved in their recognition snapshot/manifest; their original freeze correctly refuses changed implementation hashes. The completed downstream and handoff runs refuse to overwrite their existing private databases.

Final status remains **MEASURED_TECHNICAL_CEILING**. Candidate targets, safe-output/STP targets, review-rate targets, production latency qualification and independent release accuracy have not been met.
