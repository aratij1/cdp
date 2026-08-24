# CDP Phase 8.10 — Wrong-Crop Calibration

The labeled validation replay contains correct, over-crop, under-crop,
wrong-region, empty, neighbor/label, and contract-fallback cases.

| Metric | Result |
| --- | ---: |
| Recall | 95.00% |
| Precision | 55.88% |
| Detected | 34 / 420 |
| Actual wrong crops | 20 / 420 |

The detector combines independent, interpretable signals. Unresolved and low
geometry signals each have 100% precision at their own threshold; label-only is
100% precise; OCR-empty is 83.33% precise; unvalidated contract fallback supplies
50% recall at 43.48% precision. Generic OCR invalidity was removed from crop risk
because it incorrectly conflated extraction failure with localization failure.

The detector is a review/blocking signal only. It never selects or accepts an
alternative value. Contract risk is explicitly recorded rather than represented
as positive localization proof.

Artifact: `wrong_crop_corpus.json/csv`; per-signal metrics are in `summary.json`.
