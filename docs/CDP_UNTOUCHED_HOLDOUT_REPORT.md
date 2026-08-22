# Phase 11 — Untouched Frozen Holdout

## Status

`AWAITING_EXTERNAL_DATA` / `NEEDS_MORE_DATA`

The holdout governance and freeze workflow is implemented. No dataset was frozen because the repository does not contain a separately sourced, never-inspected corpus with independently governed truth. Existing calibration, validation, development-holdout, reviewed crops, and historical evaluation artifacts are ineligible for an independent production claim.

## Implemented controls

- Dataset-level attestation that the source is separate and was never used for threshold tuning, prompt tuning, OCR selection, registration adjustment, or development inspection.
- Exact document-hash, perceptual-hash, and source-ID overlap rejection against development data.
- Unique asset identities and configurable minimum document count.
- Required CMS-1500 and UB-04 representation.
- Required coverage for clean scans, fax, low contrast, rotation, skew, cropped edges, poor DPI, handwriting, multi-page documents, attachments, difficult tables, unstructured pages, duplicates, and negative/non-claim pages.
- Per-document and ground-truth SHA-256 values.
- Immutable, versioned manifest with creation timestamp, composition counts, and a tamper-evident manifest hash.
- Refusal to overwrite an existing frozen version.
- Compatibility with the existing prediction-before-independent-truth collector and evaluation gate.

## Verification

The focused holdout, backfill, overlap, evaluation-gate, and STP suite passes 22 tests.

## Inputs still required

To complete the phase operationally, data governance must provide at least 100 eligible external documents and at least 300 independently labeled fields, including CMS-1500, UB-04, and every required condition. The data owner must also provide the untouched-data attestation and evidence reference.

Until those inputs exist, overall accuracy remains 72.13%, UB-04 accuracy remains 75.93%, critical false accepts remain zero on the inspected benchmark, and safe STP remains unqualified at 0%. These are development results, not independent production estimates.
