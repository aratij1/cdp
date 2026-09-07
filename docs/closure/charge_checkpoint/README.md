# TOTAL-CHARGE CLOSURE

**CHECKPOINT_50_REACHED ? REVIEW_ONLY / ENGINEERING_ONLY.**

The unchanged frozen 30 claims improved from **51/118 (43.22%) to 64/118 (54.24%) Recall@5**. Critical coverage improved from **39/86 (45.35%) to 48/86 (55.81%)**. The checkpoint required 59/118; 13 additional fields were recovered, including 9 critical fields. Existing tokens alone reach 63/118.

This is a retrospective engineering measurement on already exposed claims, not clean validation or a production qualification. Production acceptance, routing, HITL/STP policy and canonical outputs are unchanged. The 150-page Track B cohort was not accessed. Work remains local and uncommitted.

## Current inventory

Recomputed from the 51/118 baseline. Covered means present at Recall@5. Critical and claims columns refer to misses. Zero comparable service_date/other fields remain zero; the denominator was not expanded or reduced.

| Field | Total | Covered before | Remaining before | Critical remaining | Claims affected | Remaining after |
|---|---:|---:|---:|---:|---:|---:|
| member_id | 20 | 8 | 12 | 12 | 12 | 12 |
| patient_dob | 6 | 5 | 1 | 1 | 1 | 1 |
| service_date | 0 | 0 | 0 | 0 | 0 | 0 |
| total_charge | 30 | 7 | 23 | 18 | 23 | 10 |
| principal_diagnosis | 6 | 4 | 2 | 2 | 2 | 2 |
| names | 56 | 27 | 29 | 14 | 19 | 29 |
| other | 0 | 0 | 0 | 0 | 0 | 0 |

Names comprise patient_name: 16/30 covered, 14 misses; insured_name: 11/26 covered, 15 misses. Full inventories include every one of the 67 baseline misses and 54 remaining misses in [current_miss_inventory.json](current_miss_inventory.json).

## Total-charge source audit

All 23 misses have one primary cause in [source_audit.json](source_audit.json). Mutually exclusive primary causes: wrong region/topology **5**; implied decimal **10**; split-token assembly **1**; OCR token absent **5**; only line charges visible **1**; claim total absent **1**; other **0**. These sum to 23.

Separate audit axes: visible clear **20**; visible low quality **1**; line-only **1**; source absent **1**; semantic mismatch **0**. Correct primary total digits present **16**, absent **7**. Of the 16, five contain an explicit decimal value and eleven require source-proven cents assembly. Five of the seven absent cases have visible totals and qualify for OCR. Two have no printed claim-wide total (SOURCE_VALUE_NOT_PRESENT) and remain in the denominator. These overlapping axes must not be added to primary-cause counts.

The four OTHER statement pages already contain correct summary-total tokens, but lack supported form topology. They produce no candidates. Matching numbers in service lines, units, noncovered columns, paid amounts and balances do not count as total-cell token presence.

## Why the previous 0/3 pilot failed

The old pilot covered CLM_A_001/A_002/A_003 and required full token containment within x <= 0.72 of page width plus an explicit decimal. A_001 has the correct decimal but a trailing currency glyph crosses that bound. A_002 has source-correct digits spanning the printed cents column and a currency suffix, with no OCR decimal. A_003 has a genuine character-recognition error. Enlarging the same generic window would not fix all three causes.

The new geometry uses source-hash-bound normalized cells reviewed against CMS box 28 or the UB TOTALS row intersecting column 47. CMS and UB are separate. Token provenance includes untouched raw text, bounding boxes, indices, source hash and final candidate rank. A small scan-coordinate tolerance and a bounded trailing currency glyph are allowed; mixed numeric cells are rejected. Registration was completed before secondary OCR. Parameters receive no reference value, expected digits or expected length.

## Semantics

CDP total_charge is the claim-wide charge, consistent with NSF XA0 total_claim_charges and UB Record 90 accommodation plus ancillary charges. CMS box 28 and UB TOTALS/column 47 show that amount. UB noncovered totals, units, line charges, paid amounts and balances are excluded. Record 001 is an informational summary and is not counted twice. Original owner specification hashes were verified; see [semantic_audit.json](semantic_audit.json).

A printed dollars/cents subdivision supports inserting a decimal between observed digits. Missing zeros or digit-like letters are never repaired. This iteration does not sum service lines or receipts. The two source-absent cases remain misses even though an electronic control-total definition exists; complete source-line binding and an aggregation fallback were not implemented.

## Distinct pilots

A and B inspect all 17 reviewed standard-form miss pages; attempted below counts eligible source-evidenced cases for each cause (1 and 11). Their eligible sets are disjoint. C attempted all five eligible visible-but-unrecognized cells once.

| Pilot | Attempted | Recovered | Critical | Claims improved | New candidates | New alternatives | New blockers | OCR calls | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 | 1.93 ms |
| B | 11 | 11 | 7 | 11 | 11 | 6 | 2 | 0 | 1.58 ms |
| C | 5 | 1 | 1 | 1 | 2 | 1 | 1 | 5 | 9067.04 ms |

Retained A: existing explicit-decimal localization. Retained B: source-proven numeric assembly. Retained C: bounded recognition for the distinct missing-digit cause; its one critical recovery moves CLM_B_001 from distance 2 to 1. C recovered only 1/5 and emitted one incorrect numeric alternative on CLM_A_003. That incorrect reading is preserved and counted, never silently corrected or accepted. Four no-gain OCR cases received no further tuning. See [retention_decision.json](retention_decision.json).

Latency is measured candidate-generation time plus actual OCR where applicable, not end-to-end production latency. Secondary OCR includes adapter preprocessing and initial model loading. No new primary OCR or LLM calls occurred; five secondary calls took about 9.07 seconds.

## Coverage and claim distance

| Metric | Before | After |
|---|---:|---:|
 | Recall@1 | 37/118 | 43/118 |
| Recall@3 | 47/118 | 57/118 |
| Recall@5 | 51/118 (43.22%) | 64/118 (54.24%) |
| Critical Recall@5 | 39/86 (45.35%) | 48/86 (55.81%) |
| Total-charge Recall@5 | 7/30 | 20/30 |

| Missing-field distance | Before | After |
|---|---:|---:|
| 0 | 2 | 7 |
| 1 | 8 | 7 |
| 2 | 7 | 5 |
| 3 | 7 | 7 |
| 4+ | 6 | 4 |

Five additional claims move from 1 to 0 missing fields: A_005, B_005, C_003, C_004, C_005. Four move from 2 to 1: A_001, A_010, B_001, B_003. Distance zero measures candidate coverage only; it does not authorize STP or release.

## Ambiguity and limitations

**14 new candidates, 13 correct recoveries, 1 incorrect OCR alternative.** The frozen ambiguity metric adds **8 non-equivalent alternatives** and **3 new ambiguity blockers** (A_002, A_003, B_003). Charge-pool mean size rises 1.37 to 1.83, P95 4 to 5; no field exceeds five candidates. Alternatives include differences from previously retained malformed OCR strings and are not equivalent to eight new incorrect answers.

Coverage regressions: **0**. Semantic role substitutions: **0**. Recognition errors are reported separately: **1 new incorrect OCR alternative**. Existing candidate ranks and non-charge pools remain unchanged; new values are appended. All candidates are REVIEW_ONLY / ENGINEERING_ONLY. No production call site imports this evaluation strategy.

Output failures remain **22**, safe outputs **0**; serialization was not changed. Full traces are in [candidate_traces.json](candidate_traces.json); raw source images and private token/replay material stay under evaluation_results.

## Validation and reproduction

**2,069 tests passed**, including all unit, architecture and fixed-width golden tests; two existing Starlette deprecation warnings. The 29 new focused cases cover numeric assembly, implied cents, missing-digit abstention, source identity/hash, OTHER/UNKNOWN, line and adjacent-column exclusion, OCR gates, truth-free inputs and preserved alternatives. Ruff and scoped mypy passed. Frozen 30/118/86, all 67 image hashes, owner specification hashes, append-only candidate pools and non-charge invariance passed. See [validation.json](validation.json).

Run `.venv/Scripts/python.exe -m evaluation.charge_checkpoint_replay` to replay cached, sealed pilots. `--freeze` validates an existing matching freeze and refuses replacement; `--ocr` requires the installed OCR runtime and reuses matching cached results. Implementation and input hashes are pinned in [strategy_freeze.json](strategy_freeze.json). The working Git commit is bf0ef3ce67b5aeea35ce6d9d9452a328d4d7a297. No commit or push was performed.

## Final status and next action

**CHECKPOINT_50_REACHED.**

**Next action:** Review the three new ambiguity blockers against their source-token provenance.
