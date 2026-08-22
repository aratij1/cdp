# CDP HITL reduction report

Status date: 2026-08-22. Decision: `NEEDS_MORE_DATA`.

## Measured outcome

| Metric | Baseline | Current governed result | Delta |
|---|---:|---:|---:|
| Overall field accuracy | 72.13% | 72.13% | 0.00 pp measured |
| Critical-field accuracy | 65.56% | 65.56% | 0.00 pp measured |
| Reviewed fields | 262 | 256 | -6 |
| Correct former reviews automated | 0 | 6 | +6 |
| Claim HITL rate | 76.67% | 76.67% | 0.00 pp measured |
| Safe STP rate | 0.00% | 0.00% | 0.00 pp measured |
| Perfect-claim rate | 20.00% | 20.00% | 0.00 pp measured |
| Total false accepts | 0 | 0 | 0 measured |
| Critical false accepts | 0 | 0 | 0 measured |

The truth-blind `hitl-evidence-v1` candidate safely resolves six critical-name review fields using independent RapidOCR and PaddleOCR agreement plus deterministic name/label validation. Post-seal evaluation shows 100% selective accuracy for those six decisions. They occur across claims that still contain other blocking fields, so claim-level HITL and STP do not yet change.

## Review Pareto

The leading baseline reasons are OCR disagreement (201 fields), no evidence (171), address ambiguity (154), empty crops (137), low registration confidence (122), low OCR confidence (118), invalid format (91), unstructured documents (91), multiple plausible values (85), and unverified critical names (60). Reasons are multi-label and therefore exceed the 262 reviewed fields when summed.

The frozen candidate leaves 256 reviewed fields. Its leading reasons are OCR disagreement (196), no evidence (171), address ambiguity (154), empty crop (137), low OCR confidence (118), low registration confidence (117), unstructured documents (91), invalid format (85), multiple plausible values (80), and unverified critical names (54).

## Rejected experiments

| Experiment | Reviews removed | Correct | False accepts | Decision |
|---|---:|---:|---:|---|
| Broad two-engine consensus | 37 | 11 | 26 | `REJECT` |
| Legacy value-less reference decisions | 56 | 35 | 21; 21.9% critical FAR | `REJECT` |
| Allow-listed critical-name consensus | 6 | 6 | 0 | `NEEDS_MORE_DATA` pending holdout |

Rejected candidates are retained as evidence. Multiple OCR engines can agree on the same wrong crop, and a `REFERENCE_VERIFIED` marker without its authoritative value is not sufficient acceptance evidence.

## Implemented review-avoidance evidence

- Registration: adaptive cheap alignment plus SIFT/FLANN/RANSAC fallback, registration-quality gates, wrong-crop protection, and bounded 5%/10% crop recovery.
- Reference matching: governed member, provider/NPI, and code adapters with lineage, version, contradiction, and multi-attribute safety rules.
- Secondary OCR: field-specific RapidOCR-to-Tesseract/Paddle routing and versioned preprocessing, including orientation and edge-clipping recovery.
- Deterministic evidence: field-specific acceptance policies, criticality/evidence classes, validation, checkbox geometry, non-blocking fields, claim-level STP gates, and UB-04 row/total reconciliation.
- Textract and Gemini: selective, budgeted, policy-authorized auxiliary candidate routes; neither has direct acceptance authority.
- HITL: field-level evidence, alternatives, reason codes, recommendation context, feedback persistence, and immutable evidence versions.
- Evaluation bridge: nested-schema, truth-blind optimization with sealed candidate hashes and post-seal scoring.
- Reference contract: accepted imports now retain authoritative value, provider, dataset version, and source record ID; missing values fail closed.

## Attributed reductions

| Source | Reviews safely removed | Evidence status |
|---|---:|---|
| Registration/crop recovery | 0 measured | Candidate experiment required |
| Reference matching | 0 measured | Representative authorized reference snapshot required |
| Secondary OCR | 6 | RapidOCR + PaddleOCR name agreement |
| Deterministic validation/reconciliation | 6 | Same six fields; not additive |
| Textract | 0 measured | Live provider experiment not run |
| Gemini | 0 measured | Live provider experiment not run |
| Other/non-blocking policy | 0 measured | Claim-level candidate comparison required |

## Cost and latency

Current configured planning cost is $0.76936/page: $0.00270 pre-HITL and $0.76667 HITL at the measured 76.67% claim-review rate. The six decisions reuse existing local OCR evidence, add no cloud cost, and do not eliminate a complete claim review. P95 local OCR latency remains 434.56 ms from the prior component test; no post-change end-to-end P95 is claimed.

## Promotion decision

Do not promote globally. The safe development candidate preserves zero false accepts but does not meet the `<30%` claim-HITL milestone. The available 78-row reference workbook fails the governed re-import because approval, label-strength, or contradiction requirements are incomplete. Further progress requires corrected authoritative reference records or new structural OCR evidence, then untouched-holdout confirmation.
