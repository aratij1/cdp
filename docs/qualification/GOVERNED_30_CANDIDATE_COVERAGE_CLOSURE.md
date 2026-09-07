# GOVERNED 30 CANDIDATE COVERAGE CLOSURE

Status: **CANDIDATE_COVERAGE_IMPROVED**. This is an isolated engineering candidate experiment, not a production extraction or release qualification result. Overall 98% and critical 99% targets are **not met**. No challenger or candidate rule is enabled in the production worker path.

Branch: `closure/cdp-target`. Frozen baseline commit: `75ebb518`. Track A remains 30 exact claims, 118 comparable fields, 86 critical fields. Raw accuracy remains **1/118 (0.85%)**; critical accuracy remains **1/86 (1.16%)**. Reference scoring, normalization, ranking, acceptance thresholds, truth, and form identity are unchanged.

The original 124-slot audit had 108 missing candidates. Its already-approved exclusion of six ambiguous service-date slots leaves **102 missing among 118**, plus 16 candidate-bearing slots: one correct selected, 14 wrong values, and one correct unselected alternative. This iteration does not change that denominator or exclusion.

## Candidate recall

| Metric | Frozen candidate pool | Token-only proposal pool | With eligible bounded OCR |
| --- | --- | --- | --- |
| R@1 | 1/118 (0.85%) | 7/118 (5.93%) | 7/118 (5.93%) |
| R@3 | 2/118 (1.69%) | 11/118 (9.32%) | 11/118 (9.32%) |
| R@5 | 2/118 (1.69%) | 11/118 (9.32%) | 12/118 (10.17%) |

Critical R@5: **2/86 (2.33%) → 9/86 (10.47%)**. Existing candidates keep their original order; unique token proposals and then secondary proposals are appended. Candidate@1 is not a new production selection. The correct alternative in the original ranking-miss case stays covered.

Missing candidate slots: **102 → 74**. **28** previously empty slots now contain a review-only proposal; only **10 additional fields** gain a correct value within the first five. Wrong proposals do not count as recall recovery. The final pool contains proposals for 44/118 fields.

| Field | Before R@5 | After R@5 | Newly covered | Still uncovered |
| --- | --- | --- | --- | --- |
| insured_name | 0/26 (0.00%) | 2/26 (7.69%) | 2 | 24 |
| member_id | 0/20 (0.00%) | 2/20 (10.00%) | 2 | 18 |
| patient_dob | 0/6 (0.00%) | 0/6 (0.00%) | 0 | 6 |
| patient_name | 2/30 (6.67%) | 5/30 (16.67%) | 3 | 25 |
| principal_diagnosis | 0/6 (0.00%) | 0/6 (0.00%) | 0 | 6 |
| total_charge | 0/30 (0.00%) | 3/30 (10.00%) | 3 | 27 |

Provider name is not represented in the frozen comparable slots. Service date remains excluded under the prior mapping audit; neither is assigned a new denominator here.

## Missing-candidate failure matrix

All 102 originally empty slots have exactly one primary stage. These are **new-capture replay diagnoses**, not reconstructed original worker logs; those logs did not retain the required token trace. Zero counts do not prove that a stage never failed historically.

| Primary stage | Fields |
| --- | --- |
| NO_LOCALIZATION | 54 |
| WRONG_REGION | 0 |
| EMPTY_CROP | 0 |
| OCR_NO_TOKENS | 0 |
| OCR_WRONG_TEXT | 9 |
| TOKEN_FILTERED | 0 |
| ASSEMBLY_FAILED | 28 |
| FIELD_RULE_TOO_NARROW | 7 |
| REFERENCE_NOT_VISIBLE_ON_SOURCE | 4 |
| OTHER | 0 |

The highest-priority shared blocker is total-charge localization (12 critical slots), followed by member-ID localization (10), patient-name localization (9), and patient-name assembly (8). The companion blocker artifact ranks critical count, affected claims, frequency, and field family. Actual claim unlock remains unproven because review and output blockers remain.

## Source visibility and OCR evidence

The original run persisted no full OCR token stream: its in-memory cache is gone, stored candidate token arrays are empty, and OCR audit records contain call metadata. Therefore the requested original-token split is **unknown for all 102 missing slots**. Unbound legacy OCR caches were not attributed to this run.

A new, explicitly labeled primary-engine capture used the same PaddleOCR PP-OCRv4 adapter and 1,600-pixel full-page cap on all **67 hash-verified prepared pages**. This was a primary evidence recapture, not multi-engine full-page escalation. Individual-line comparison found **47/102** references present and **55/102 not matched**. Name word-order equality is included. This is not exhaustive cross-token/date assembly and must not be called proof that 55 values are absent from OCR.

Engineering pixel inspection covers all 118 fields. Among the 102 missing slots: **89 VISIBLE_CLEAR, 7 PARTIAL, 2 OVERPRINTED, 4 NOT_PRESENT**, and zero VISIBLE_LOW_QUALITY/ILLEGIBLE. The four absent values are insured-name placeholders without a corresponding name in the semantic source field. They remain in the denominator and are not generated from pixels. Relational name cells, truncated/initialed names, identifier punctuation differences, and a multi-receipt aggregate require evidence-aware assembly; this iteration does not alter the comparator to force matches. Several prepared pages are rotated 180 degrees.

## Bounded localization and assembly

The retained experiment associates individual label tokens with the next two local rows, bounded by neighboring columns and at most 5% of page height. It handles OCR-confusable characters only in label recognition, preserves identifier characters, and uses the existing last/first interpretation only with source label or comma evidence. It does not merge unrelated columns or globally expand windows.

CMS name/member/charge labels provide explicit anchors. UB name labels can be associated, but terse birth-date labels and the unlabeled principal-diagnosis box remain localization gaps. A UB charge-column header alone is insufficient: the experiment requires a visible TOTALS row and charge-column intersection. The service-line crop that appeared to match a claim total was rejected. Receipts and other layouts receive no fixed CMS/UB coordinate fallback. Review-only proposals confer no standard-form identity or canonical authorization.

## Bounded OCR failure cohort

Nine initial regions were tried with RapidOCR. Final provenance auditing excludes one invalid service-line region and one redundant patient-name trial already covered by token assembly. Seven remaining regions received bounded CLAHE contrast processing and the supported Paddle adapter. One confirmed handwritten charge region attempted TroCR; optional ML dependencies were unavailable, so it produced no inference. Printed claims were not sent through handwriting OCR.

There were **24 attempts, 23 completed OCR calls**, including the two excluded trials. The seven eligible regions produced **one incremental R@5 recovery (1/7, 14.29%)**, the insured name at rank 4. CLAHE added no incremental match. A matching patient-name OCR result was redundant, not a second recovery. No output from the invalid charge crop enters the final pool.

Primary recapture: **314.15 seconds** total. Candidate replay including local image/hash reads: **5.37 seconds**. Secondary trials including excluded work: **114.42 seconds**. Maximum observed post-call process RSS: **536.24 MiB**; this is not peak memory or isolated engine memory. Primary-capture memory was not measured. The bounded experiment does not establish an acceptable production latency budget; challengers remain disabled.

Reference values are used only by evaluation, failure classification, and gate assertions. The generator takes OCR geometry and image dimensions only. Capture helpers accept an exact source-only schema and reject reference-bearing keys. Crop coordinates originate from label/token evidence, never the expected value. The post-trial gate rejects missing provenance, already available token/assembly values, absent/partial source values, and unconfirmed handwriting.

## Separate ranking and downstream lanes

The single `CLM_D_006 / patient_name` ranking miss remains separate. A broad selected line had confidence 0.943; the narrower correct alternative had 0.867. OCR confidence did not establish semantic correctness. No ranking changes are retained. The 14 wrong-value cases have their own classification artifact; they are not relabeled as 14 ranking failures.

At both candidate milestones, routing is recomputed from the sealed field inventory, decisions and tasks. Because proposals are not emitted into production validation, there are **zero actual routing transitions**: auto accepted **0**, HITL **16**, not emitted **102**, not eligible **6**, unknown **0**. No synthetic transition is credited for a shadow candidate. Claim HITL remains **30/30 (100%)**; true STP remains **0/30**. This is an evidence reconciliation, not a replay of new proposals through runtime workers.

Output remains a separate lane: **22 failures**, all the previously recorded `OUTPUT_REQUIRES_STANDARD_FORM_TYPE:UNSTRUCTURED`, and **0 safe outputs**. Candidate recall does not conceal those failures. No new critical false accepts can arise from this disabled experiment; production acceptance evidence remains unchanged.

## Track B and validation

Source-only UI: http://127.0.0.1:8094/qualification-review/ — HTTP 200, predictions hidden. Bindings **150/150**; membership confirmed **0**, remaining **150**; completed reviews **0**; trusted fields **0**. The owner-confirmation watcher is running. Continuity checks created no reviews and loaded no predictions. Independent reviewer registration remains pending.

Validation: **1,882 unit/architecture/golden tests passed**, **19 focused tests also passed** for the provenance and OCR gates. Scoped Ruff and mypy passed. Historical fixed-width goldens, strict identity, three false-UB04 canaries, and OTHER/UNKNOWN safety are included. **NEW_SEMANTIC_REGRESSIONS = 0** in this test scope; OTHER canonical localization = 0, UNKNOWN canonical localization = 0 in the canary/safety tests. No external-service integration or new production latency qualification is claimed.

PHI-bearing source images, OCR text, references and candidate values remain in ignored local evaluation storage. Published artifacts contain aliases, classifications and aggregate counts only. Original input hashes and acceptance-policy hashes are verified before every replay.

Reproduce candidate measurement with `.venv/Scripts/python.exe -m evaluation.governed_30_candidate_coverage`; then publish the aliased artifacts with `.venv/Scripts/python.exe -m evaluation.governed_30_candidate_report`. This requires the local sealed source/capture evidence. The source-only capture helpers live in `evaluation/governed_30_token_capture.py`; selected OCR adapters require the separate OCR environment.

## Next action

Add one source-evidenced claim-total anchor for a no-localization failure, then replay the frozen 30-claim cohort.
