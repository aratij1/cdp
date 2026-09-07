# Largest recoverable cohort closure

**MAJOR_COVERAGE_GAIN**. Retained one strategy: source-reviewed name-cell row assembly. The frozen 30-claim replay recovered **18 fields, including 9 critical fields, across 12 claims**. No new OCR calls were made.

## Baseline and measured result

| Metric | Before | After | Delta |
| --- | --- | --- | --- |
| Comparable fields | 118 | 118 | 0 |
| Recall@5 | 25/118 (21.1864%) | 43/118 (36.4407%) | +18; +15.2542 percentage points |
| Critical Recall@5 | 22/86 (25.5814%) | 31/86 (36.0465%) | +9; +10.4651 percentage points |
| Remaining candidate misses | 93 | 75 | -18 |

Recall@1 increased from 17/118 to 29/118; Recall@3 increased from 23/118 to 39/118. Existing candidate order is preserved and new values are appended. No before-covered field regressed at ranks 1, 3, or 5. There were zero baseline misses with the correct candidate already below rank five.

## Remaining taxonomy at the 25/118 baseline

| Recoverability category | Fields |
| --- | --- |
| RECOVERABLE_FROM_EXISTING_TOKENS | 8 |
| RECOVERABLE_WITH_SOURCE_PROVEN_GEOMETRY | 25 |
| RECOVERABLE_WITH_TOKEN_ASSEMBLY | 21 |
| RECOVERABLE_WITH_ORIENTATION | 5 |
| TRUE_OCR_RECOGNITION_MISS | 13 |
| SOURCE_SEMANTIC | 2 |
| SOURCE_ABSENT | 4 |
| SOURCE_ILLEGIBLE | 0 |
| REFERENCE_NOT_DIRECTLY_EXTRACTABLE | 15 |

These are diagnostic categories, not guaranteed recoveries. The inventory explicitly marks unproven cases. Whole-page token coincidences are recorded separately from own-field-region availability; patient/insured cross-copying and principal/admitting diagnosis substitution are prohibited. Prior orientation captures are reused. Five remaining orientation-category cases still need source analysis; no orientation/OCR branch was added. Semantic, absent, abbreviation, punctuation and derived-aggregate cases were not sent for OCR recovery.

The name feasibility audit found 18 fields, and the full replay recovered all 18. The two charge-region numeric coincidences were only provisional upper bounds: the charge pilot required an explicit monetary token and recovered zero. They must not be treated as proven claim totals. All 93 inventory records retain field, form, criticality, alias, visibility, token availability, localization, candidate status, cause, recoverability, and claim distance.

## Ranked recoverable cohorts and pilots

| Rank / family | Potential fields | Critical | Claims | Pilot recovery | Pilot critical | Pilot claims improved |
| --- | --- | --- | --- | --- | --- | --- |
| 1. NAME_CELL_ROW_ASSEMBLY | 18 | 9 | 12 | 4/5 | 1 | 3 |
| 2. MEMBER_ID_CELL | 6 | 6 | 6 | 2/2 | 2 | 2 |
| 3. TOTAL_CHARGE_CELL | 2 | 1 | 2 | 0/2 | 0 | 0 |

Ranking is based on own-region token evidence, then critical impact and potential candidate-complete claims. Unverified failure families remain in `failure_family_aggregation.json` and the full inventory; they are not assigned invented recovery promises. Pilots used at most two initial claims plus one additional claim when required to cover another form. The name pilot initially covered CMS only; UB coverage was added before selecting the winner. Pilot execution is isolated from the subsequent full replay.

Selection uses pilot recovery rate multiplied by cohort size, then estimated critical recovery and claim unlocks. Names projected 14.4 field recoveries and 7.2 critical recoveries with one potential unlock; identifiers projected 6 and 6 with no immediate unlock. These projections are heuristic, not statistical estimates. Measured full recovery was 18 and 9. Identifier discovery stays an evaluation-only pilot; charge discovery is a no-op. Neither is applied in the full replay.

## Source-reviewed anchor contract

The retained discovery mechanism uses a common `SourceReviewedAnchor` contract with source SHA-256, form and field identity, anchor region, allowed candidate region, version, source-review provenance and coordinate-frame rotation. The registry contains geometry and provenance only. It rejects truth-bearing schema fields. A public discovery API checks exact image bytes, token-source hash, form identity, field identity, review provenance, version and rotation before row assembly. OTHER, UNKNOWN, UNSTRUCTURED and mismatched forms abstain.

Source-only visual review established repeated layouts on 17 CMS pages and six UB pages. A reusable normalized form topology supplies the regions, with observed CMS label/address boundaries; no per-image procedural branch was added. The registry binds generated regions to each reviewed source image. Form identity here is explicitly an engineering source-review identity: it neither rewrites the frozen worker classification nor authorizes canonical output. Sources without that identity remain outside this bounded experiment.

Names are assembled only from tokens in their own reviewed cell. Source punctuation and reviewed LAST/FIRST layout permit reordering and row joining; no dictionary, reference string, character correction, initial expansion, placeholder inheritance or cross-person copy is used. Candidates remain review-only. The source-review manifest was built from pixel inspection before candidate generation. References are confined to feasibility auditing and scoring, never supplied to the generator.

## Claim distance

| Candidate blockers | Before | After |
| --- | --- | --- |
| 0 | 0 | 1 |
| 1 | 3 | 5 |
| 2 | 4 | 9 |
| 3 | 11 | 8 |
| 4+ | 12 | 7 |

One claim (CLM_A_011) reaches candidate-complete state. This is not auto acceptance or production claim completion. Detailed per-claim remaining and critical misses are in the before/after distance artifacts.

## OCR, latency and candidate noise

New primary OCR: **0**. Secondary OCR: **0**. LLM calls: **0**. Additional in-memory name discovery took **4.407 ms** across the 23 reviewed source pages in this local replay. This includes repeated source-hash checks but excludes pre-existing OCR and initial source loading; it is not a production latency benchmark.

43 new unique candidate values were added. 18 match a newly covered governed field; 25 do not match the governed reference. This candidate-noise count includes raw-order alternatives and unrepaired OCR errors. These are visible review-only alternatives, not accepted field errors. The existing candidate order is unchanged, so no previously correct top-five value is displaced.

## Safety and independent closure lanes

Truth-bearing registry keys are rejected. Hash binding, strict form identity, OTHER/UNKNOWN abstention, field boundaries, rotation mismatch, candidate ordering, and no OCR repair are covered by regression tests. **NEW_SEMANTIC_REGRESSIONS = 0** within the tested production/coverage scope. This does not claim every new alternative is semantically correct. Production acceptance, thresholds, canonical extraction and outputs were not changed. The 22 frozen output failures remain separate and their raw evidence remains hash-sealed.

Track B was checked through read-only progress and binding summaries only: 150 bindings intact; reviewed pages 0; owner-confirmed memberships 0/150; trusted fields 0. UI is live. Binding and membership hashes match the prior continuity snapshot. No reviews were submitted, no predictions requested, and no Track B data used for development.

## Validation and reproduction

**1,967 unit, architecture and fixed-width golden tests passed**, including 33 new focused tests. Ruff and scoped mypy passed. The suite reported two existing Starlette deprecation warnings. Exact sources, OCR snapshots, frozen reference, original execution and acceptance policy are verified by the input seal; all 67 source image hashes are checked. Local evidence contains private strings; public reports use aliases, coordinates, hashes and aggregates.

Run `.venv/Scripts/python.exe -m evaluation.governed_30_cohort_optimization` for inventory and pilots. After reviewing passing pilots, run the same module with `--replay` for the selected strategy. Sealed local artifacts are required.

## Checkpoint and next action

The 50% engineering checkpoint is **not reached**: 43/118 is 16 fields short of 59/118. No global recoverability ceiling has been proven. Even excluding 21 semantic/source-absent/reference-contract cases gives only a loose upper bound of 97/118, not evidence that all remaining fields are recoverable. No production-readiness claim is made.

**Next action:** Apply the successful source-reviewed identifier-cell pilot to the six existing-token member-ID misses, then replay the frozen 30 claims.
