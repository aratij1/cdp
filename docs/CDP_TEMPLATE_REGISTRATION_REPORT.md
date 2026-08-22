# CDP Phase 2 — Canonical Template Registration

## Decision

**NEEDS_MORE_DATA.** The CMS-1500 02/12 canonical package is implemented and integrity-checked. UB-04 remains deliberately unavailable because the identified official CMS archive rejected automated retrieval. The cross-family fresh evaluation therefore remains closed instead of substituting a non-authoritative or PHI-bearing image.

## Implemented

- Deterministic canonical package builder from an approved blank PDF.
- CMS-1500 package containing `canonical.png`, `version.json`, `anchors.json`, `fields.json`, and SIFT `descriptors.npz`.
- SHA-256 integrity checks for the canonical image and descriptor bundle.
- Exact template identity, dimensions, provenance, PHI status, descriptor version, and registration-algorithm version checks.
- Automatic registry discovery of canonical packages when no operator reference is configured.
- Fail-closed readiness behavior for incomplete, altered, unknown-PHI, or wrong-version packages.

The CMS-1500 source is the official NUCC 02/12 form PDF. NUCC states that version 02/12 took effect April 1, 2014 and publishes the PDF as a non-submission reference. CMS likewise identifies 02/12 as the current version and warns that downloaded copies are not valid claim-submission stock:

- https://www.nucc.org/index.php/1500-claim-form-mainmenu-35
- https://www.cms.gov/medicare/billing/electronicbillingeditrans/1500

The selected page is an unpopulated public sample: it contains no patient or provider data. The visible `SAMPLE` watermark is retained rather than altered; its registration impact must be measured before promotion.

CMS identifies CMS-1450 and UB-04 as the same institutional form and provides a public reference through its PRA listing, but CMS also explains that it does not supply submission forms:

- https://www.cms.gov/Regulations-and-Guidance/Legislation/PaperworkReductionActof1995/PRA-Listing-Items/CMS-1450
- https://www.cms.gov/Medicare/Billing/ElectronicBillingEDITrans/1450

## Evidence

| Check | Result |
|---|---:|
| CMS-1500 canonical dimensions | 1712 × 2214 |
| CMS-1500 SIFT keypoints | 12,946 |
| CMS-1500 image SHA-256 | `8b77133ac2fc84817d855073f0e26b7ecd20f1da6b6a6a099c01d06f565d113e` |
| CMS-1500 descriptor SHA-256 | `071fa4f75f22d29ce6e56aee0576de964ac3266e34527ad9accacc24bf989dbb` |
| Registry-ready forms | CMS-1500 |
| Registry-blocked forms | UB-04 |
| Focused tests | 23 passed |

## Metric impact

No accuracy claim is made in this phase because the required all-family fresh run is blocked by the missing lawful UB-04 reference. Baseline remains 72.1311% overall accuracy, 65.5556% critical accuracy, zero false accepts, and 76.6667% claim-level review. Runtime inference cost and latency are unchanged; template building is an offline operation.

## Next gate

Obtain the official public CMS-1450 archive through an approved network path or provide an operator-approved non-PHI blank UB-04 image. Build and validate `templates/ub04`, then execute fresh crop generation, registration evaluation, OCR inference, and the full safety comparison. No template-dependent auto-acceptance should be enabled before that gate passes.
