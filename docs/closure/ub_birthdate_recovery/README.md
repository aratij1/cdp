# UB birth-date recovery

**INCREMENTAL_GAIN ? ENGINEERING_ONLY.** The frozen UB box-10 rule recovered both targeted source-visible birth dates without new OCR.

| Metric | Before | After |
| --- | --- | --- |
| Recall@5 | 49/118 (41.53%) | 51/118 (43.22%) |
| Critical Recall@5 | 37/86 (43.02%) | 39/86 (45.35%) |
| UB birth-date Recall@5 | 3/6 | 5/6 |

Recovered fields: patient_dob on CLM_C_001 and CLM_C_004. Each uses eight observed source digits formatted as MMDDYYYY into ISO date notation. One trailing underscore may be removed as the previously reviewed rule-line artifact. No OCR character repair, century inference, reference-derived hint, date inheritance or neighboring admission-date copy is allowed. Invalid calendar dates and competing valid dates within the cell cause abstention. CLM_C_002 still contains an OCR letter and remains unresolved.

The rule uses the unchanged normalized region from the successful date pilot and strict UB/patient_dob identity. It is source-value independent; source image and OCR hashes are checked separately through the engineering review catalog. Canonical production form identity is not rewritten.

The implementation, parameters and 49/118 baseline were sealed in `birthdate_strategy_freeze.json` before six-claim UB engineering validation. Validation passed with two recoveries and no loss. Only then was the same 30-claim, 118-field, 86-critical-field cohort replayed; all 67 source images were hash checked. The full-replay gate binds to the exact validated strategy hash.

**NO_CLEAN_VALIDATION_AVAILABLE:** all six UB claims are in one previously exposed package. This is an engineering validation, not package-independent generalization. No production promotion follows.

Exactly two unique candidates were added. There were zero new equivalent duplicates, non-equivalent alternatives, ambiguity blockers or coverage regressions. Mean candidates per birth-date field rose from 1.000 to 1.333; P95 stayed 4; fields above five stayed zero. All non-birth-date candidate pools, including the name and member-ID recoveries, remain unchanged.

| Claim blockers | Before | After |
| --- | --- | --- |
| 0 | 2 | 2 |
| 1 | 7 | 8 |
| 2 | 7 | 7 |
| 3 | 8 | 7 |
| 4+ | 6 | 6 |

Two claims improved; the number of candidate-complete claims remains two. Candidate completeness is not production acceptance or STP.

Primary OCR calls: 0. Secondary OCR calls: 0. LLM calls: 0. Additional in-memory generation took 0.278 ms; source/hash reads and prior OCR costs are excluded. This is not a production latency measurement.

Production acceptance, routing, thresholds and canonical outputs remain unchanged. The downstream lane still has 22 output failures and zero safe outputs. Track B was not accessed.

The 19 focused rule tests cover strict form/field identity, leap years and calendar errors, forbidden character repairs, compact-date interpretation, scale invariance, neighboring-cell rejection, competing dates and truth-free schema. **2,040 unit, architecture and fixed-width golden tests passed**, with two existing Starlette deprecation warnings. NEW_SEMANTIC_REGRESSIONS = 0 in this tested scope. Ruff and scoped mypy passed.

Reproduce the frozen six-UB engineering check with `.venv/Scripts/python.exe -m evaluation.ub_birthdate_replay`, then add `--full` only after its gate passes. Private sealed evidence is required. Raw date values remain in ignored local replay artifacts; public audits contain aliases, counts and ranks only.
