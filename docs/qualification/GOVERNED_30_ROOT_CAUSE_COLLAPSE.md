# CANDIDATE COVERAGE ROOT-CAUSE COLLAPSE

**FINAL STATUS: RECOVERABLE_COVERAGE_IMPROVED**. All **106 original remaining misses** have exactly one concrete primary cause. No UNKNOWN/OTHER case remains. The official engineering denominator stays **118** across **30 exact Track A claims**.

Candidate Recall@5 improved from **12/118 (10.17%)** to **21/118 (17.80%)** in the combined review-only experiment. Critical Recall@5 improved from **9/86** to **18/86 (20.93%)**. **97 misses remain**. The 98% target is not met. Production extraction, canonical output, acceptance, scoring, ranking, and release truth are unchanged.

The geometry/assembly change alone reaches **19/118 (16.10%)**. Two further fields require the explicitly **manually verified orientation diagnostic**. No automated orientation detector or secondary OCR challenger is enabled in production. Baseline commit: `b954b200`, branch `closure/cdp-target`.

## Miss taxonomy

These counts classify the original 106 misses, not a newly reduced denominator. The 118-field audit also records each retained experiment and whether the original miss was recovered. Evidence consists of frozen OCR token indices, label/value boxes, page/column relationships, distances, candidate-region provenance and source-visibility annotations. This is a reconstructed engineering trace, not fabricated historical worker telemetry.

| Primary cause | Original misses |
| --- | --- |
| SOURCE_VALUE_NOT_PRESENT | 4 |
| SOURCE_PLACEHOLDER_SEMANTICS | 2 |
| REFERENCE_ABBREVIATION_OR_EQUIVALENCE | 14 |
| ORIENTATION_FAILURE | 15 |
| LABEL_TO_VALUE_ASSOCIATION | 6 |
| REGION_LOCALIZATION | 31 |
| TOKEN_ASSEMBLY | 14 |
| OCR_RECOGNITION_MISS | 9 |
| SOURCE_ILLEGIBLE | 0 |
| WRONG_FORM_OR_FIELD_TOPOLOGY | 11 |
| OTHER | 0 |

Matching text elsewhere on a page is not assigned to the target field. In two UB claims, the correct-looking code appears in the admitting-diagnosis cell while the principal cell contains a different recognized code; these are recognition misses. Four other principal-diagnosis values are present in their actual box-67 region but lack a supported field anchor. Name component-order evidence is treated as assembly only when local label/value geometry supports it. Three initially suspected recognition misses instead contain observed amount components or a merged numeric span; they are assembly failures. A UB charge-column header without a proven totals-row intersection is a topology failure, not a grounded total OCR region.

## Extractable source cohort and conditional ceiling

**EXTRACTABLE_SOURCE_FIELDS: 97**. **NONEXTRACTABLE_OR_SEMANTIC_REFERENCE_FIELDS: 21**. The latter comprise four absent insured-name values represented by reference placeholders; two source name cells saying SAME without a governed inheritance rule; fourteen abbreviation, fixed-width truncation, nickname or identifier-punctuation differences; and one reference total requiring aggregation across two distinct receipts.

These 21 cases remain in the official 118. Visible full names and punctuated identifiers are still extractable as source text; “semantic” here means they cannot be credited as the frozen reference value under the current governed comparison contract. No fake name, abbreviation, stripped identifier or reference-derived total is generated.

Diagnostic recoverable Recall@5: **12/97 (12.37%) → 21/97 (21.65%)**. Within the 97 source-present fields there are zero established genuinely unavailable cases, so `(97 - 0) / 97 = 100%` is a **conditional logical upper bound**, not a demonstrated OCR ceiling. Keeping the 21 semantic cases unresolved gives a corresponding 97/118 (82.20%) bound on literal frozen-reference recovery. Neither calculation rewrites the official denominator or qualifies a release. No claim of an empirical OCR ceiling is made.

## Candidate and field results

| Experiment | R@1 | R@3 | R@5 | Critical R@5 |
| --- | --- | --- | --- | --- |
| baseline | 7/118 (5.93%) | 11/118 (9.32%) | 12/118 (10.17%) | 9/86 (10.47%) |
| orientation | 9/118 (7.63%) | 13/118 (11.02%) | 14/118 (11.86%) | 11/86 (12.79%) |
| geometry | 11/118 (9.32%) | 17/118 (14.41%) | 19/118 (16.10%) | 16/86 (18.60%) |
| combined | 13/118 (11.02%) | 19/118 (16.10%) | 21/118 (17.80%) | 18/86 (20.93%) |

The candidate pools retain original emitted selections/alternatives. New geometry operates on observed labels and source token boxes. A proven birth-date/sex compound anchor replaces the generic birth-date row proposal set, because neighboring sex/admission values are not date alternatives. Eight observed digits are assembled with the existing US date convention; characters and centuries are never repaired or inferred. This changes field localization and candidate filtering, not confidence ranking or the comparator.

The following source-semantic and cause counts refer to the original taxonomy; recall columns show the final combined diagnostic.

| Field | Comparable | R@1 | R@3 | R@5 | Semantic | Localization/association/topology | Assembly | OCR | Absent/illegible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| member_id | 20 | 1/20 (5.00%) | 2/20 (10.00%) | 2/20 (10.00%) | 7 | 8 | 0 | 0 | 0 |
| provider_name | 0 | N/A | N/A | N/A | 0 | 0 | 0 | 0 | 0 |
| patient_name | 30 | 4/30 (13.33%) | 6/30 (20.00%) | 7/30 (23.33%) | 4 | 12 | 3 | 2 | 0 |
| insured_name | 26 | 1/26 (3.85%) | 1/26 (3.85%) | 2/26 (7.69%) | 9 | 8 | 2 | 1 | 4 |
| patient_dob | 6 | 3/6 (50.00%) | 3/6 (50.00%) | 3/6 (50.00%) | 0 | 1 | 5 | 0 | 0 |
| service_date | 0 | N/A | N/A | N/A | 0 | 0 | 0 | 0 | 0 |
| total_charge | 30 | 4/30 (13.33%) | 7/30 (23.33%) | 7/30 (23.33%) | 1 | 15 | 4 | 4 | 0 |
| principal_diagnosis | 6 | 0/6 (0.00%) | 0/6 (0.00%) | 0/6 (0.00%) | 0 | 4 | 0 | 2 | 0 |

Provider name has no comparable slot in this frozen cohort. Service date remains outside these 118 under the previously sealed mapping decision. No zero-denominator percentage is fabricated.

## Retained changes and orientation diagnostic

Seven critical fields recover through bounded field geometry/assembly: three birth dates using an observed field-10 birth-date/sex relationship, three claim totals including observed dollar/cents assembly, and a label-local name token. The separate six-page orientation diagnostic recovers two more critical fields. No previously covered field is lost.

- `CLM_A_007 / total_charge` — field geometry / typed date assembly.
- `CLM_A_012 / patient_name` — reviewed orientation.
- `CLM_B_002 / total_charge` — reviewed orientation.
- `CLM_B_004 / total_charge` — field geometry / typed date assembly.
- `CLM_C_003 / patient_dob` — field geometry / typed date assembly.
- `CLM_C_005 / patient_dob` — field geometry / typed date assembly.
- `CLM_C_006 / patient_dob` — field geometry / typed date assembly.
- `CLM_D_004 / total_charge` — field geometry / typed date assembly.
- `CLM_D_005 / patient_name` — field geometry / typed date assembly.

Geometry uses distinct family bounds, neighboring column boundaries and observed label/value coordinates. A service charge-column header still cannot authorize a claim total. Candidate values come only from observed tokens or explicit date assembly. Runtime APIs accept no reference value, and proposals remain review-only.

Orientation audit: **67 pages** examined using local OSD, then structural grid comparison. There were **16 OSD inversion flags**: **14 visually confirmed inverted pages** and **2 upright false positives**. No page passed the conservative automatic OSD gate or the joint grid/OSD gate. Six inverted pages contained the audited governed target fields and were recaptured with the same PaddleOCR PP-OCRv4 primary engine. Eight separator/support pages outside those target fields were not sent through additional OCR.

Affected-field token presence (whole-line/component comparison): **1/16 → 12/16**. OSD audit cost **62.75s**; structural-grid audit cost **5.31s**. The six same-primary captures cost **39.32s**, versus **34.55s** for their prior unrotated captures: observed delta **4.77s**. These sequential local measurements are not a controlled production latency benchmark. The final four-mode replay took **18.57s** including image/hash reads. No global preprocessing change is retained.

## Semantic contract and rejected proposals

The supplied `NSF_matrix.txt` and `UB92_specs.txt`, their compiled output contracts, and existing claim consistency policy provide no explicit rule copying a patient name into a SAME insured-name cell. Existing SELF logic checks equality only when both names are independently observed and unambiguous; it does not create missing values. The two name-placeholder cases stay unresolved. Eight exact placeholder lexemes observed in existing OCR are inventoried separately; a printed SELF checkbox option is not proof it was selected.

The existing name comparator permits formatting differences, not initial/full-name equivalence or arbitrary truncation. The member-ID comparator preserves punctuation. These rules were audited and tested without modification.

Rejected proposals:

- **Automatic orientation:** no conservative evidence gate passed; two low-confidence OSD false positives demonstrate the need to abstain. Costs are recorded above; no production semantic impact.
- **Broader fuzzy name-convention inference:** no incremental Recall@5 recovery in the all-30 replay; removed instead of adding complexity. No OCR calls were added; replay cost was approximately 16 seconds. No acceptance or output impact.
- **SAME/SELF inheritance and abbreviation rewriting:** no authorizing governed rule; zero runtime candidates or OCR calls created.
- **Global or expanded secondary OCR:** not performed. Prior invalid-region and redundant recoveries stay excluded; source semantics, association and assembly cases are not sent to challengers.

## Residual recognition benchmark

There are **9 recognition-classified misses**. A bounded audit of two-to-four neighboring tokens in their observed label neighborhoods found no additional reference match. Existing prior region trials cover **4** of those fields: **12 completed region calls** across RapidOCR, CLAHE and Paddle, plus **one failed optional handwriting-model attempt**. They produced **zero recoveries** in this residual cohort, with **50.56s** historical measured trial time. These prior results are reused, not credited as new work or rerun. The remaining recognition fields are not declared exhausted. **New secondary OCR calls: 0.**

## Separate routing, output and Track B lanes

Frozen runtime events, field inventory, decisions and tasks were reconciled for the candidate milestones. Review-only proposals are not worker emissions, so actual transitions remain zero: **AUTO_ACCEPTED 0; HITL 16; NOT_EMITTED 102; NOT_ELIGIBLE 6; UNKNOWN 0**. No field suppression is credited. Claim HITL remains **30/30 (100%)**; true STP **0/30**. Raw production accuracy remains **1/118**, critical accuracy **1/86**.

Output remains **22 failures** (`OUTPUT_REQUIRES_STANDARD_FORM_TYPE:UNSTRUCTURED`) and **0 safe outputs**. No output-contract patch is mixed into this iteration.

Track B: source-only UI http://127.0.0.1:8094/qualification-review/ is live (HTTP 200, predictions hidden). Source bindings **150/150**; owner-confirmed membership **0/150**, remaining **150**; completed reviews **0**; trusted fields **0**. Owner-confirmation watcher remains active. No review was written and no prediction was loaded for tuning.

## Validation and evidence

**1,916 unit, architecture and fixed-width golden tests passed**; **34 focused structural/semantic/orientation tests passed**. Scoped Ruff and mypy passed. Tests cover strict identity, OTHER/UNKNOWN safety, false-UB04 canaries, source-only input schemas, immutable identifiers, placeholder abstention, compound topology, invalid dates, cross-column isolation and the preserved charge-column guard. **NEW_SEMANTIC_REGRESSIONS = 0** in this regression scope. Canonical production output is unchanged. No external-service integration or production latency qualification is claimed.

Raw sources, OCR strings, reference values and private candidate evidence remain in ignored local evaluation storage. Published artifacts contain aliases, boxes, classifications and aggregates. Frozen source/capture and acceptance-policy hashes are verified by replay.

Reproduce with `.venv/Scripts/python.exe -m evaluation.governed_30_root_collapse`, then `.venv/Scripts/python.exe -m evaluation.governed_30_root_collapse_report`. Local sealed evidence is required. Reviewed rotation capture has a source-only helper in `evaluation/root_collapse_capture.py`; it does not enable automatic rotation.

## Next action

Add a source-proven box-67 principal-diagnosis anchor for the four cases whose correct tokens are already in that cell, then replay the frozen 30 claims.
