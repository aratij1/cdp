# CDP Synthetic Benchmark Audit

The current dataset is PHI-free and deterministic, but it is not production-representative.

- Evaluated fields: 600
- Errors: 6
- Proven label/data ROI overlaps among errors: 0
- System/OCR errors after excluding proven rendering overlaps: 6
- Service-line labels: absent
- Production holdout qualification: false

## Finding

No populated data ROI contains a template label in the corrected renderer. The remaining failures are system/OCR errors on this synthetic set.
