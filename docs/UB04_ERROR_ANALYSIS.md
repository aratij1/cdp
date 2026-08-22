# UB-04 Error Analysis and Specialized Service-Line Engine

## Current measured position

The latest governed benchmark reports UB-04 field accuracy of 75.93%. This phase does not claim a new accuracy result because the existing development documents were already inspected and no untouched UB-04 holdout or approved canonical reference image is available.

## Observed failure groups

Current mismatch artifacts show these recurring modes:

- Crop and label contamination: patient-name crops include printed labels such as admission, birthdate, and sex.
- Registration/crop placement: federal tax ID, provider NPI, sex, and type-of-bill regions are sometimes blank or shifted.
- Numeric parsing: type-of-bill and diagnosis values lose or gain leading/trailing digits.
- Confidence misinterpretation: legacy OCR can be highly confident on truncated or label-contaminated values. Phase 5 evidence policies prevent confidence-only acceptance.
- Reference validation: NPI and HCPCS authority is unavailable for some paths, so these remain review-bound.
- Table geometry and service-line association: the prior shadow pipeline emitted independent cells but did not provide a production-grade row object with total reconciliation.

The present evaluation contract has limited labeled UB-04 service-line truth. Consequently, table-specific accuracy and review reduction cannot yet be measured honestly.

## Phase implementation

`UB04ServiceLineEngine` reconstructs FL42–FL48 values from registered token geometry before parsing any value. It:

- assigns tokens to one of 22 configured rows and seven semantic columns;
- preserves row association and left-to-right token order;
- parses four-digit revenue codes, HCPCS, compact or separated dates, units, covered charges, and non-covered charges;
- validates HCPCS against an injected governed reference when available;
- requires revenue code and charge for an active row;
- reconciles the sum of line charges with the claim total to one cent;
- prevents automatic eligibility for invalid, incomplete, low-confidence, or reference-unverified rows;
- routes low-confidence or unreliable geometry to Docling;
- routes structurally invalid or total-mismatched results to HITL.

## Safety and next evidence requirement

No generic threshold was lowered. The engine remains fail-closed, and no row is automatically eligible based on OCR confidence alone. Promotion requires an approved UB-04 reference template, governed HCPCS reference data, and a new untouched holdout containing labeled service lines and difficult-table cases.
