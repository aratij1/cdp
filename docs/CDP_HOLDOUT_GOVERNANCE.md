# CDP Holdout Governance

Status: `PRODUCTION_HOLDOUT_V1` is `NOT_FROZEN` / `NEEDS_MORE_DATA`.

No independently sourced, never-inspected production-representative corpus or data-owner attestation is available in the repository. `dataset_raw/` was used during development, `evaluation_data/` is synthetic/development material, and `evaluation_results/` contains derived outputs. They are explicitly rejected and were not repackaged as a holdout.

The production target is at least 200 documents, 250 pages, and 1,000 labeled field observations: at least 100 CMS-1500 and 100 UB-04 documents; field-specific samples for all eight blocking fields; at least 600 C2 and 300 C3 observations; and clean, degraded, severe, and handwriting/unstructured quality buckets. Required composition includes digital and office scans, fax, DPI variation, geometry defects, compression/noise, handwriting/fonts, bundles/attachments, duplicate and negative pages, blanks/optional fields, service-line tables, and unstructured attachments.

Every eligible asset requires document SHA-256, every page SHA-256, truth SHA-256, source identity, family, quality bucket, field/criticality counts, and conditions. The freeze adds dataset version, creation timestamp, source description, composition, sample targets, and a tamper-evident manifest hash. Exact, perceptual, and source overlap with development data are rejected.

The attestation prohibits OCR selection, thresholds, ROI, registration, preprocessing, evidence/claim policy, blocking fields, route selection, confidence calibration, prompts, and reference-match tuning. Once unsealed, holdout errors may reject a release or request more data but may not tune it.

The current readiness record is `evaluation/holdout/manifest.json`. It contains zero assets and is intentionally not a frozen evaluation manifest.
