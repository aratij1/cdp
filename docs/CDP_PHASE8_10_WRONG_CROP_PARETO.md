# CDP Phase 8.10 — Wrong-Crop Pareto

## Result

Wrong-crop/firewall precision is 100.00%, recall is 45.10%, and no wrong-crop signal is allowed to authorize acceptance. Precision passes; recall does not.

The remaining false negatives are primarily geometrically owned crops that the independent truth benchmark classifies as excess-area or wrong-region. Runtime cannot use truth to recover them. Broadening the firewall to reject every large character-relative crop increased recall but also blocked correct OCR, so that setting was not promoted.

The observed localization outcomes across 420 validation fields are:

| Outcome | Count |
|---|---:|
| Value contained | 380 |
| Over-crop | 27 |
| Wrong region | 4 |
| Empty region | 3 |
| Under-crop | 2 |
| Geometric match | 4 |

Residual action order:

1. Recover corrupted/missing anchors using independently registered structural cells.
2. Add field-cell ownership evidence that can distinguish a valid wide cell from a multi-field crop.
3. Calibrate the firewall on additional development sources; do not tune against validation or the locked holdout.

Machine-readable evidence is in `evaluation_results/phase8_10/wrong_crop_corpus.json` and `localization_records.jsonl`.
