# Box-67 candidate recovery

The same frozen 30 claims (67 pages, 118 comparable fields, 86 critical fields) were replayed against the sealed candidate pools from commit 907575e9. Four principal-diagnosis misses were recovered by appending existing OCR tokens from source-reviewed box-67 interiors.

| Metric | Before | After | Delta |
| --- | --- | --- | --- |
| Recall@1 | 13/118 | 17/118 | +4 |
| Recall@3 | 19/118 | 23/118 | +4 |
| Recall@5 | 21/118 (17.7966%) | 25/118 (21.1864%) | +3.3898 percentage points |
| Critical Recall@5 | 18/86 (20.9302%) | 22/86 (25.5814%) | +4.6512 percentage points |

Recovered fields: principal diagnosis for CLM_C_003 through CLM_C_006. Six raw candidates were added, one per reviewed institutional source. The two other principal OCR readings remain incorrect; admitting-diagnosis values were not substituted. There were no coverage regressions and no new OCR calls.

## Source evidence and limits

The six source images were visually inspected in a source-only contact sheet. Each reviewed region is the first diagnosis-cell interior right of the printed 66 DX area, in the upper diagnosis band above the separate 69 admitting-diagnosis row. Literal 67 is not reliably printed or recognized on these copies. The supplied UB topology identifies this cell as principal diagnosis. The annotation contains coordinates and source provenance only, with no expected diagnosis values.

`source_anchors.json` binds each manual engineering annotation to exact image bytes. The generator checks both image and OCR-source hashes, requires the complete token box to lie inside the reviewed region, and preserves the raw OCR reading. It receives no reference, claim alias, expected form, or target diagnosis. Unanchored source images generate no proposals. These six hash-bound annotations are a bounded diagnostic intervention, not a general UB detector or trusted release annotation.

Generation runs over all 67 sealed source pages before the evaluator opens the reference-bearing baseline rows. Existing combined pools retain their ordering; new proposals are appended, then the frozen comparator measures Recall@1/3/5 with unchanged denominators. Previously reviewed orientation recovery and secondary candidates remain in those baseline pools. The reused OCR is the earlier primary-engine recapture, not tokens persisted by the original worker run.

All additions are review-only. No worker acceptance, routing, canonical form identity, output authorization, reference normalization, or release-truth state was changed. This measures candidate coverage, not production extraction accuracy.

## Reproduction

Run `.venv/Scripts/python.exe -m evaluation.governed_30_box67_replay` from the repository root with the sealed local source and baseline artifacts available. `input_seal.json` pins baseline records, summary, capture manifest, primary-token files, original raw execution, reference, and acceptance policy. Every source image is independently hash-checked. A changed input stops the replay.

`scorecard.json` contains measured metrics and evidence hashes. Private candidate values, token indices, bounding boxes and page checks remain under `evaluation_results/governed_30_box67`; source pixels and diagnosis values are not included in this report.

## Validation

Unit, architecture and golden suites: **1,934 passed**, including 18 new source-anchor tests. Ruff and scoped mypy passed. The regression suite emitted two existing Starlette deprecation warnings. Final replay reproduced the four recoveries with no lost Recall@1, @3 or @5 coverage.
