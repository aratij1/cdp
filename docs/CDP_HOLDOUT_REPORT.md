# CDP holdout report

Status date: 2026-08-22. Decision: `AWAITING_EXTERNAL_DATA` / `NEEDS_MORE_DATA`.

The untouched-holdout freeze and overlap-rejection workflow is implemented, but the repository does not contain an eligible separately sourced corpus with independently governed truth. Existing development, calibration, reviewed-crop, historical evaluation, and synthetic artifacts are ineligible for a production-generalization claim.

The gate requires at least 100 external documents and 300 independently labeled fields; CMS-1500 and UB-04 coverage; representative clean, fax, low-contrast, rotated, skewed, cropped-edge, poor-DPI, handwriting, multi-page, attachment, difficult-table, unstructured, duplicate, and negative pages; data-owner attestation; and document, truth, perceptual, and source-identity overlap checks.

Until those inputs are provided, the only governed figures remain 72.13% overall accuracy, 65.56% critical accuracy, 75.93% UB-04 accuracy, zero observed false accepts on the inspected development benchmark, 76.67% claim review, and 0% qualified safe STP. These are not production estimates.

See `CDP_UNTOUCHED_HOLDOUT_REPORT.md` for the detailed freeze controls and operational inputs.
