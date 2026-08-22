# CDP registration report

## Implemented

The structured-form path uses a cheap alignment attempt followed by SIFT keypoints, FLANN matching, Lowe filtering, RANSAC homography, and explicit quality metrics. Field extraction is blocked or expanded when registration/crop evidence is unsafe; crop margins of 0%, 5%, and 10% are supported. Canonical packages are versioned and checksum protected, and include image, descriptors, anchors, fields, dimensions, DPI, source provenance, and algorithm versions.

CMS-1500 `02-12` has a complete non-PHI package sourced from the official NUCC blank at `templates/cms1500`. UB-04 geometry exists at `config/templates/ub04_v2014.yaml`, including 22 service rows, but no canonical image is activated.

## UB-04 source gate

CMS identifies CMS-1450 and UB-04 as the same institutional form and publishes a downloadable PRA copy. On 2026-08-22 the CMS CDN returned Access Denied to both PowerShell and browser-user-agent downloads in this environment. The implementation deliberately did not label a generated approximation as an official canonical form. Production UB-04 registration therefore remains fail-closed until an operator supplies the official public blank and runs:

```powershell
python -m evaluation.build_canonical_template --source <official-pdf> --source-url <cms-url> --source-authority CMS --page <zero-based-page> --template-id ub04 --version 2014
```

After import, acceptance requires package integrity tests, visual field overlays, and stratified rotation/scale/translation/crop/photocopy tests. No accuracy gain is claimed before those measurements.
