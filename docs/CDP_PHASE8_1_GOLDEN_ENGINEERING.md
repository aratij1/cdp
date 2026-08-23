# CDP Phase 8.1 Golden Engineering Evaluation

## Dataset and integrity

- Dataset: `CDP_GOLDEN_ENGINEERING_PACK_V1`
- Archive SHA-256: `27adda09b553900c047ebdadef70a57d2a450ad0baa5989d7fe4a65fb2518119`
- Scope: 100 PHI-free synthetic pages (50 CMS-1500-like, 50 UB-04-like), 950 field truth rows, and 146 UB service-line truth rows.
- The harness verifies every manifest image hash before running. This is an engineering dataset, not production accuracy authority.

## Method

The unchanged Phase 8 dynamic path was measured first as `baseline`. It used one canonical RapidOCR full-page observation per page. Candidate runs reused those serialized observations to isolate component changes while executing real selective regional RapidOCR. The accepted implementation was then rerun uncached as `final_uncached` for end-to-end latency and reproducibility.

No router thresholds were tuned, no models were added, and no cloud OCR was called.

## Results

| Metric | Unchanged baseline | Final uncached |
|---|---:|---:|
| CMS field localization | 31.45% | 87.45% |
| CMS expected value in region | 46.00% | 88.18% |
| CMS OCR accuracy given correct localization | 81.82% | 80.82% |
| CMS final priority-field accuracy | 52.00% | **91.82%** |
| UB field localization | 22.75% | 81.25% |
| UB expected value in region | 35.25% | 81.25% |
| UB OCR accuracy given correct localization | 51.77% | 80.92% |
| UB final priority-field accuracy | 32.75% | **92.75%** |
| Critical-field accuracy | 52.00% | **93.47%** |
| UB service-line row recall | 88.36% | 88.36% |
| UB service-line exact-row accuracy | 0.00% | 59.59% |
| UB service-line column-cell accuracy | 1.83% | 83.33% |
| Secondary OCR invocation rate | 0.00% | 28.32% |
| Full-page OCR calls/page | 1.00 | 1.00 |
| Cloud calls / common-path cloud cost | 0 / $0 | 0 / $0 |

Final end-to-end latency on the evaluation host was P50 11,367.66 ms, P95 16,968.11 ms, P99 18,652.18 ms, and maximum 21,599.66 ms.

Final false accepts were 9/950 (0.947%), meeting the defined near-zero engineering envelope of at most 1%. They are deliberately retained in the evidence records rather than hidden by relaxed canonicalization.

## Failure-layer Pareto

The unchanged baseline produced 556 field-localization failures and 114 OCR failures, making localization the dominant layer. The final run produced 140 localization failures, 155 OCR failures, and 655 primary-observation passes. The residual UB service-line failures were 42 column-assignment failures and 17 table-reconstruction failures, with 87 exact rows.

## Component remediation

- Field localization now prefers bounded observed value-token geometry below a matched label and isolates the nearest same-baseline field rather than merging neighboring fields.
- Dynamic extraction selects the single datatype-valid token from a broad structural ROI where possible.
- Selective regional RapidOCR is invoked only after primary deterministic validation fails; invalid secondary evidence cannot replace primary evidence.
- Regional OCR upscales small crops and reconstructs reading order with line clustering, avoiding one-pixel vertical jitter that reversed names.
- Name reconciliation removes one isolated OCR artifact only when the independent primary compact sequence proves it extraneous. Registered labels are rejected as values.
- UB service lines infer semantic columns from observed headers and rows from observed y-clusters, reusing canonical tokens without per-cell OCR.

## Reproduction

```powershell
.\.venv\Scripts\python.exe evaluation\phase8_1_golden.py --run-id final_uncached
```

Machine-readable evidence is under `evaluation_results/phase8_1/baseline/` and `evaluation_results/phase8_1/final_uncached/`.
