# Name topology generalization

**SOURCE_SPECIFIC_ONLY ? generalization gate FAIL.** The retrospective numerical gate passed, but the validation packages had already been used in the prior fitted experiment. The unchanged 43/118 result remains engineering recovery evidence, not out-of-sample proof.

## Preserved fitted result

Recall@5: **43/118 (36.44%)**. Critical Recall@5: **31/86 (36.05%)**. Recovery: **18 fields across 12 claims**. New unique candidates: **43**. The original 25 non-reference alternatives remain a legacy count, supplemented below with reference-independent ambiguity metrics.

`fitted_result_freeze.json` records the full Git baseline SHA from Git metadata, the uncommitted implementation state, and hashes for 96 immutable snapshot files: prior candidate pools, primary and oriented OCR tokens, manifests, source-reviewed registry, implementations, references, replay records and reports. Raw/private snapshots remain under `evaluation_results/name_topology_generalization/fitted_43_snapshot`. The historical reports and measured candidate pools were not overwritten.

The checkout is still based on `bf0ef3ce67b5aeea35ce6d9d9452a328d4d7a297`; the previous cohort optimization is local/uncommitted. Its live implementation now resolves provenance through `validated_baseline_sha`, rejects a mismatched checkout, and contains no literal baseline SHA. The snapshot retains the original implementation. Nothing was pushed in this iteration.

## Package-isolated retrospective split

| Partition | Packages | Claims | Forms |
| --- | --- | --- | --- |
| NAME_TOPOLOGY_DEV | 2: A and D | 19 | CMS engineering slots; only source-reviewed CMS pages train geometry |
| NAME_TOPOLOGY_VALIDATION | 3: both B packages and C | 11 | CMS and UB |

Package overlap: **0**. Claim overlap: **0**. Source-image overlap: **0**. Exact membership and source hashes are in the split manifests. The split was assigned from package identities, before this iteration?s rule development and without reference-based selection. Validation includes five CMS claims and six UB claims, including a reviewed inverted CMS page.

The cohort has only one UB package. Keeping it in validation leaves no UB development package, so no UB topology was invented. All 30 claims had prior development exposure, including the inherited name assembler. A fresh split cannot erase that exposure. This limitation is enforced as an independent gate veto.

## Development isolation and freeze

The development module reads only DEV source labels, token geometry, and source identity metadata. It does not load reference records, candidate values, historical recovery records, or validation OCR. A file-access guard test proves those files are not read on this path. Reference partition preparation occurs only after the topology freeze passes integrity validation.

The new experimental `NameFieldTopology` has separate CMS patient and insured contracts, normalized regions, alignment rules, maximum token gap, row tolerance and provenance version. It contains no image hash, name, reference value, reference length or expected initials. UB patient and insured contracts are explicitly unsupported because DEV supplies no UB package.

Page dimensions handle scan scaling. Bounded registration transforms handle small translations and deskew without enlarging the region; excessive transforms abstain. This experiment uses the existing prepared coordinate frame and does not claim a newly validated automatic registration detector. Labels and address boundaries constrain each CMS column. SAME, SAME AS ABOVE and SELF yield unresolved source-placeholder observations, never invented names.

`name_topology_freeze.json` seals the DEV manifest and implementation hashes. A pre-typecheck freeze was retained separately; only type annotations changed before validation. No topology parameter, candidate assembly rule, or frozen implementation changed after validation. A later evaluator-only integrity guard checks the source-identity catalog; it did not alter candidates or trigger a validation rerun.

## DEV and validation name recall

| Metric | DEV before | DEV after | Validation before | Validation after |
| --- | --- | --- | --- | --- |
| R@1 | 4/35 (11.43%) | 5/35 (14.29%) | 1/21 (4.76%) | 5/21 (23.81%) |
| R@3 | 6/35 (17.14%) | 9/35 (25.71%) | 1/21 (4.76%) | 7/21 (33.33%) |
| R@5 | 8/35 (22.86%) | 11/35 (31.43%) | 1/21 (4.76%) | 7/21 (33.33%) |
| Critical name R@5 | 7/19 (36.84%) | 8/19 (42.11%) | 0/11 (0.00%) | 3/11 (27.27%) |

Validation improved six name fields across four claims, with zero Recall@5 losses and zero new OCR calls. These are retrospective diagnostics. The 35 DEV and 21 validation name fields are the existing comparable name subset; overall denominators remain the frozen 118/86. No comparable field was added or removed.

| Validation contract | Before R@5 | After R@5 |
| --- | --- | --- |
| CMS1500 patient_name | 0/5 (0.00%) | 3/5 (60.00%) |
| CMS1500 insured_name | 0/4 (0.00%) | 3/4 (75.00%) |
| UB patient_name | 0/6 (0.00%) | 0/6 (0.00%) |
| UB insured_name | 1/6 (16.67%) | 1/6 (16.67%) |

UB figures reflect baseline candidates only; the new rule abstained for all UB fields. They are not a test of learned UB generalization.

## Candidate ambiguity

Candidate counts and correct ranks before/after are published per field. The ambiguity diagnostic groups punctuation/case/order variants having identical lexical tokens. This is **observed-token equivalence**, not verified person-identity equivalence, and is never used to merge candidates or authorize acceptance. Lexically different alternatives form distinct groups. A new ambiguity blocker means a field moves from at most one such group to more than one.

| Validation name metric | Before | After |
| --- | --- | --- |
| Mean candidates | 0.952 | 1.476 |
| P95 candidates | 3 | 4 |
| Fields with >5 candidates | 0 | 0 |
| Token-equivalent duplicates | 3 | 10 |
| Non-equivalent alternatives | 9 | 9 |

Validation new non-equivalent ambiguity blockers: **0**. Maximum additions per field: **2**. Frozen bounds were a maximum of four additions per field and mean candidate delta at most two; both passed.

For the historical fitted 43/118 replay, mean name candidates increased **1.536 ? 2.304**; P95 stayed **5 ? 5**; fields above five increased **1 ? 2**; token-equivalent duplicates **16 ? 41**; non-equivalent alternatives **40 ? 44**; new ambiguity blockers **1**. This is more informative than treating all 25 non-reference alternatives as equally harmful.

## Audit of the 18 historical recoveries

The post-freeze audit contains no name strings and was not used to derive this iteration?s geometry. It records source form, field, token count, row relation, column relation, label relation, normalized candidate/anchor boxes and token gaps. CMS contributed nine recoveries: four patient and five insured. UB contributed nine: five patient and four insured. Seventeen recoveries use a single OCR token with punctuation/order assembly; one CMS patient recovery joins multiple tokens. All recovered tokens remain in their own field columns.

## Generalization gate and full replay

The retrospective numerical checks pass: **+28.57 percentage points** in validation name Recall@5, zero loss, bounded ambiguity, strict form guards, zero current-development reference reads and zero new OCR. **The independence gate fails**, because validation was previously exposed. UB generalization additionally lacks a DEV package. This is failure to establish generalization, not proof that the architecture could never generalize.

**No new full-30 replay was run.** The gate requires independent validation before that step. The preserved fitted full-cohort result remains 25/118 ? 43/118 and critical 22/86 ? 31/86; it is not relabeled as the new rule?s full result. Preserved fitted claim-distance buckets for 0/1/2/3/4+ blockers remain **1 / 5 / 9 / 8 / 7**. Ranking optimization is deferred. The new topology stays in experimental evaluation code and is not promoted toward canonical shadow evaluation.

## Output, Track B and validation

Output failures: **22**. Safe outputs: **0**. Production acceptance changed: **NO**. Canonical output changed: **NO**. No STP improvement is claimed. Track B was not accessed in this iteration. Its 150-page blind cohort remains outside development and ranking.

**1,992 unit, architecture and fixed-width golden tests passed**, with two existing Starlette deprecation warnings. The final source-catalog integrity adjustment also passed all **25 focused tests**. Ruff, formatting and scoped mypy passed. Tests cover package isolation, validation-reference access, normalized scale/translation/deskew, independent field/form contracts, placeholders, ambiguity accounting, schema leakage, source/provenance integrity and OTHER/UNKNOWN safety. **NEW_SEMANTIC_REGRESSIONS = 0** in this tested scope.

Reproduce source-only DEV derivation and freeze with `.venv/Scripts/python.exe -m evaluation.name_topology_development`. The freeze refuses implementation or manifest changes. Post-freeze scoring is `.venv/Scripts/python.exe -m evaluation.name_topology_validation`; it verifies provenance and immutable inputs and reports the independence failure explicitly. Private source evidence is required.

## Next action

Select the next largest recoverable non-name cohort.
