# Non-name cohort closure

**MAJOR_NON_NAME_GAIN ? ENGINEERING_ONLY.** One retained strategy, normalized CMS member-ID cell discovery, recovered **six critical fields across six claims**. Clean validation was unavailable; this is not a production generalization result.

## Baseline and full replay

| Metric | Before | After | Delta |
| --- | --- | --- | --- |
| Recall@5 | 43/118 (36.44%) | 49/118 (41.53%) | +6 fields; +5.08 percentage points |
| Critical Recall@5 | 31/86 (36.05%) | 37/86 (43.02%) | +6 fields; +6.98 percentage points |
| Candidate-complete claims | 1 | 2 | +1 |

All **30 claims, 118 comparable fields and 86 critical fields** were preserved. All 67 source-image hashes were checked before the full replay. New discovery ran on the existing source-reviewed page identities; unsupported source identities abstained. Non-member-ID candidate pools, including all fitted name and box-67 results, stayed byte-for-byte equal as value lists. The 43/118 measurement and SOURCE_SPECIFIC_ONLY name work remain hash-frozen.

The checkout was inspected before work: `closure/cdp-target`, HEAD `bf0ef3ce67b5aeea35ce6d9d9452a328d4d7a297`. Later name and cohort work remained local/uncommitted. This iteration did not push or change branches.

## Non-name inventory and top five

There were **46 non-name misses**: 23 total charges, 18 member IDs, three birth dates and two principal diagnoses. Names were excluded from optimization. The four solved box-67 cases were not counted again. The inventory records source visibility, historical and validated token availability, candidate status, root/failure stage, criticality, current claim distance and recovery outcome.

| Rank | Field | Remaining misses before | Evidence-backed recoverable | Critical | Claims | Strategy |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | member_id | 18 | 6 | 6 | 6 | NORMALIZED_ID_CELL |
| 2 | patient_dob | 3 | 2 | 2 | 2 | OBSERVED_EIGHT_DIGIT_DATE |
| 3 | total_charge | 23 | 0 | 0 | 0 | EXPLICIT_MONEY_IN_CLAIM_TOTAL_CELL |
| 4 | principal_diagnosis | 2 | 0 | 0 | 0 | ABSTAIN_ON_WRONG_BOX67_OCR |
| 5 | service_date | 0 | 0 | 0 | 0 | NO_COMPARABLE_SLOT_UNDER_FROZEN_MAPPING; NOT_A_RECOVERY_OPPORTUNITY |

Service date has no comparable slot under the already-frozen mapping; its fifth entry is explicitly ineligible, not an invented recovery opportunity. Charge-region digit coincidences rejected earlier were excluded from recoverability counts. The two remaining diagnosis misses still have wrong principal-cell OCR; correct admitting-diagnosis tokens cannot substitute. The birth-date opportunity consists of two source-visible numeric dates, with the third containing an unrepaired OCR letter.

## DEV pilots and selection

| Pilot | Attempted | Recovered @1 / @3 / @5 | Critical recovered | Claims improved | New candidates | New non-equivalent alternatives |
| --- | --- | --- | --- | --- | --- | --- |
| member_id | 3 | 3 / 3 / 3 | 3 | 3 | 3 | 0 |
| patient_dob | 2 | 2 / 2 / 2 | 2 | 2 | 2 | 0 |
| total_charge | 3 | 0 / 0 / 0 | 0 | 0 | 0 | 0 |

Every pilot used zero new OCR calls. Per-pilot latency is in `pilot_results.json`. Member IDs won on projected field recovery (six), critical impact (six), and one potential claim unlock. Birth-date recovery remained an evaluation-only pilot; the charge pilot recovered nothing and was not applied beyond DEV. Exactly one primary strategy was retained.

## Package exposure and frozen validation

DEV: **A+C, two packages, 18 claims**. Validation: **both B packages+D, three packages, 12 claims**. Package, claim and source-image overlap are zero. Splits were assigned before pilot tuning. All packages had prior engineering exposure, so the recorded exposure is **NO_CLEAN_VALIDATION_AVAILABLE**.

The reference materializer streams past disallowed top-level records without accumulating or decoding them. Tests prove DEV materialization never decodes validation reference records. Validation reference access fails before the strategy freeze exists and rejects changed frozen implementations. A source-image/form catalog and OCR hashes are verified before use. The generic discovery API receives no reference values, lengths, characters or expected identity.

`non_name_strategy_freeze.json` seals normalized geometry, filters, fragment assembly, maximum proposals, append-only ordering, code hashes and package manifests before validation scoring. The strategy did not change after validation.

| Selected-field Recall@5 | Before | After |
| --- | --- | --- |
| DEV member ID | 0/9 (0.00%) | 3/9 (33.33%) |
| Validation member ID | 2/11 (18.18%) | 5/11 (45.45%) |
| Full member ID | 2/20 (10.00%) | 8/20 (40.00%) |

Validation recovered three fields with no Recall@5 loss, critical regression, wrong-form proposal, new ambiguity blocker or OCR call. The bounded engineering validation gate passed before the full-30 replay. Generalization remains **ENGINEERING_ONLY**, because the validation packages are not clean.

## Retained mechanism and literal semantics

The rule uses a normalized CMS1500 box-1a member-ID region, strict form/field identity, and an observed insured-name label as a lower boundary when available. It accepts observed alphanumeric identifiers containing digits, preserves leading zeros, hyphens and slashes, and never repairs characters or removes punctuation to match the reference. Contiguous fragments can join only within half an observed character width and the same row; visible spacing does not license concatenation. At most two source-ordered proposals are permitted per page/field.

The reusable rule contains no image hash or patient-specific value. The replay separately binds source-reviewed form identities to exact image and OCR hashes. Those identities are engineering source-review evidence, not a rewrite of production form classification. UB, OTHER, UNKNOWN, UNSTRUCTURED and mismatched field identities produce no member-ID proposals. No new hash-specific anomaly anchors were needed.

The six recoveries were CLM_A_003, CLM_A_005, CLM_A_008, CLM_B_001, CLM_B_002 and CLM_B_005. Each came from an existing whole OCR token in its own member-ID cell. Value-free token-to-region-to-filter-to-rank traces are published in `recovered_token_traces.json`; all six newly correct candidates land at rank 1. The earlier reviewed rotation captures for A_003 and B_002 were reused, with no new OCR.

## Claim distance

| Candidate blockers | Before | After |
| --- | --- | --- |
| 0 | 1 | 2 |
| 1 | 5 | 7 |
| 2 | 9 | 7 |
| 3 | 8 | 8 |
| 4+ | 7 | 6 |

CLM_B_002 moved from one blocker to zero. The previous candidate-complete claim remains complete. Candidate-complete does not mean accepted, output-valid or straight-through processed. Remaining non-name misses: **40**; total remaining comparable misses: **69**.

## Candidate ambiguity and rank

| Member-ID metric | Before | After |
| --- | --- | --- |
| Mean candidates/field | 0.80 | 1.35 |
| P95 candidates/field | 3 | 3 |
| Fields with >5 candidates | 1 | 1 |
| Equivalent duplicates | 0 | 0 |
| Non-equivalent alternatives | 11 | 11 |

**11 unique candidates** were added: six recover missing governed values; five are non-reference source readings, including unchanged identifier punctuation. No existing candidate was reordered. New equivalent duplicates: **0**; new non-equivalent alternatives: **0**; new ambiguity blockers: **0**. These counts use the frozen field comparator and distinct-alternative groups; the first proposal into an empty field is not counted as a competing alternative. This does not declare every singleton correct. The five unmatched source readings remain review-only.

Correct member-ID rank distribution changed from **18 absent / 1 at rank 1 / 1 at rank 3** to **12 absent / 7 at rank 1 / 1 at rank 3**. The previously existing field with more than five candidates was not worsened. Across all 118 fields, mean candidate count changed **1.678 ? 1.771**, P95 stayed **5**, and fields above five stayed **3**.

## OCR, latency, safety and independent lanes

New OCR calls: **0**. Secondary OCR: **0**. LLM calls: **0**. Additional in-memory discovery cost: **1.116 ms** across 23 reviewed source pages; source loading, hashing and existing OCR are excluded. This is a local engineering measurement, not a production latency guarantee.

Wrong-form proposals: **0**. OTHER/UNKNOWN localization: **0**, enforced by strict identity tests. Reference-derived generator inputs: **0**. Coverage and critical regressions: **0**. **NEW_SEMANTIC_REGRESSIONS = 0** in the tested scope. Production acceptance, confidence thresholds, routing and canonical output are unchanged. The 22 output failures and zero safe outputs remain a separate downstream lane; no STP improvement is claimed. Track B was not accessed or used for development, validation or ranking.

## Validation and reproduction

**2,021 unit, architecture and fixed-width golden tests passed**, including **29 focused non-name tests**. Ruff, formatting and scoped mypy passed. Two existing Starlette deprecation warnings remain. Tests cover field localization, normalized geometry, fragmented IDs, leading zeros, punctuation, package/source isolation, validation-reference decoding guards, ambiguity, frozen provenance, wrong/unknown forms, unchanged names and fixed denominators. Tests requiring private replay artifacts are skipped when those artifacts are absent.

Run DEV pilots with `.venv/Scripts/python.exe -m evaluation.non_name_experiment`. Freeze the selected strategy with `--freeze`; an incompatible second freeze fails. Run `.venv/Scripts/python.exe -m evaluation.non_name_replay validation`, then `... full` only after the frozen engineering validation gate passes. Sealed local evidence is required. `frozen_input_hashes.json` protects the name work and prior baseline; source, reference and OCR seals are verified separately.

## Final status and next action

**MAJOR_NON_NAME_GAIN**, qualified as **ENGINEERING_ONLY / NO_CLEAN_VALIDATION_AVAILABLE**. Recall@5 is 49/118; the 50% checkpoint still requires ten additional fields.

Validate the two source-visible birth-date recoveries with a frozen UB-aware date-cell rule.
