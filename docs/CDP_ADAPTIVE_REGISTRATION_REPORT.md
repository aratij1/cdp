# CDP Phase 3 — Adaptive Registration and Wrong-Crop Prevention

## Decision

**NEEDS_MORE_DATA.** The adaptive registration and critical-crop safety implementation is complete and fail-closed. It cannot yet be promoted as an accuracy or review-reduction improvement because UB-04 has no approved canonical reference and the CMS-1500 public sample only registered 7 of 12 inspected development scans.

## Implemented

- Cheap edge phase-correlation alignment followed by SIFT, FLANN KNN, Lowe filtering, RANSAC, homography, and perspective warp.
- Registration evidence now records source and template keypoints, candidate and good matches, inliers, inlier ratio, reprojection error, source/template coverage, scale change, rotation, perspective distortion, transformed-corner validity, processing time, and a bounded confidence score.
- Homographies fail closed on insufficient matches/inliers, poor coverage, excessive reprojection error, unsafe scale/rotation/perspective, or invalid corners.
- Critical fields receive a separate geometry check before regional OCR: registration status, confidence, field bounds, expected local form structure, and neighboring structure must agree.
- Suspicious critical crops are marked `WRONG_CROP_SUSPECTED` and cannot remain automatically valid even when OCR confidence is high.
- Registration confidence in `[0.60, 0.80)` enables exactly three crop variants: original, 5%, and 10%. Multi-crop disagreement is routed to review. No variants are added outside that band.

## Development evidence

The canonical CMS-1500 reference was compared with the 12 existing Group A development scans. Seven registrations passed every transform gate and five were rejected with explicit reasons. The rejected cases included degenerate transforms, insufficient inlier ratios, unsafe projective distortion, and invalid transformed corners.

This 58.33% registration acceptance rate is diagnostic only. The dataset was previously inspected and is not an untouched holdout. Rejection is preferable to wrong-field OCR, but the current public reference is not sufficient to reduce review safely across the full CMS-1500 population.

## Tests and cost

- Focused plus architecture tests: 52 passed.
- Static checks: passed.
- Added cloud cost: $0.
- Added local latency: input-dependent and not yet benchmarked on an untouched representative corpus.
- False accepts introduced: 0 in the available regression suite.
- Accuracy/review deltas: not claimed; the cross-family evaluation remains blocked by the missing UB-04 reference.

## Limitations and next gate

- The NUCC public CMS-1500 image contains a visible `SAMPLE` watermark that can reduce feature-match quality.
- UB-04 registration cannot be evaluated until an approved non-PHI canonical form is available.
- Label proximity currently uses local printed-form structure matching; semantic OCR of the expected label should be benchmarked before enabling any broader auto-acceptance.
- Expanded crop comparison is deliberately conservative: disagreement adds review rather than selecting the highest-confidence value as truth.

The next ordered phase is authoritative reference matching. That work can proceed independently for local/test providers, but no registration-dependent STP promotion is justified yet.
