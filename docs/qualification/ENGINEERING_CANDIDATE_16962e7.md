# CMS-1500 engineering candidate 16962e7

Candidate: `16962e70e3a74eaea20251e9af421fe840841fa7`.

The same 12 local scans were freshly processed with existing OCR models, then compared with the same 21 frozen engineering labels. Exact accuracy increased from **0/21 to 8/21 (38.1%)**; critical accuracy is **8/19 (42.1%)**. The result is an engineering diagnostic, not production qualification.

## Measurement integrity

All 12 source hashes, the frozen truth seal, the original OCR receipt, and the candidate runtime manifest matched. The join uses unique source/page/canonical-field slots; six missing predictions remain in the denominator. The complete 21-row value-free mismatch matrix remains in authorized local governed storage. No scans, patient values, OCR strings, or labels are included in this repository receipt.

| Metric | Result |
|---|---:|
| Baseline exact accuracy | 0/21 (0%) |
| New exact accuracy | 8/21 (38.1%) |
| Critical exact accuracy | 8/19 (42.1%) |
| Normalized accuracy | Not evaluated: no approved engineering comparison contract |
| Accepted precision | N/A: 0 accepted labeled fields |
| Critical accepted precision | N/A: 0 accepted critical fields |
| Field HITL required, labeled fields | 21/21 (100%) |
| Claim HITL required | 12/12 (100%) |
| Runtime STP eligible | 0/12 |
| STP_SAFE runtime flag | 0/12; not a qualification result |
| False accepts, labeled fields | 0; no automatic accepts |
| Output completed | 0/12 |

## Accuracy by field family

| Field | Exact correct / labeled |
|---|---:|
| principal_diagnosis | 3/3 |
| provider_npi | 2/4 |
| federal_tax_no | 2/3 |
| patient_name | 0/4 |
| patient_address | 0/1 |
| insured_id_number | 0/1 |
| total_charge | 1/2 |
| provider_name | 0/1 |
| insured_address | 0/1 |
| patient_dob | 0/1 |

## Root-cause audit

These are conservative trace classifications. A zero means no remaining case was proven to belong exclusively to that category; it does not prove absence of that failure mode. The separate full-page diagnostic located 16 reference strings, 12 outside the saved review regions, so review-region overlap alone is not used as causal proof. Diagnostic source matches never become pipeline predictions.

| Classification | Before | After |
|---|---:|---:|
| CORRECT | 0 | 8 |
| LOCALIZATION | 10 | 0 |
| FIELD_MAPPING | 0 | 0 |
| OCR_RECOGNITION | 2 | 0 |
| NORMALIZATION | 0 | 0 |
| VALIDATION | 0 | 0 |
| OTHER | 9 | 13 |

The 13 unresolved mismatches comprise six missing canonical predictions, three cases with reference-matching evidence that was not selected or had row ambiguity, one partial source-span overlap, and three reference strings not recovered in the independent full-page diagnostic. These findings do not justify labeling all residual failures as OCR errors.

## Runtime changes

- Use integrity-checked public NUCC geometry after verified CMS identity and registration, including late registration fallback.
- Map Box 2 to patient_name, 3 to patient_dob, 7 to insured_address, 21A to principal_diagnosis, 24J to provider_npi, 25 to federal_tax_no, 28 to total_charge, and 31 to physician/supplier provider_name.
- Keep rendering-provider row conflicts unresolved; do not substitute billing NPI, tax ID, or an arbitrary first row.
- Recognize verified single-line value crops directly with the existing RapidOCR recognizer; retain the existing score floor. General regions still use detection. Cache entries distinguish line recognition from region detection.
- Preserve crop objects, raw and normalized values, OCR evidence, model/confidence metadata, and registration provenance. Map header and service-cell evidence back to source coordinates.
- Fix Tesseract TSV literal-quote parsing, printed-label punctuation, the federal-tax label zone, and spurious 180-degree projection ties. Enable the canonical router by default.
- Bound existing RapidOCR thread pools and deserialize persisted OCR token geometry correctly.

Acceptance thresholds, acceptance policies, criticality policies, Track B inputs, frozen labels, and the historical candidate freeze were not changed.

## Validation and limitations

Final candidate validation: **2,298 passed, 94 skipped**, two dependency deprecation warnings. The scope includes unit, architecture, and integration tests. Repository-wide Ruff, architecture checks, governed mypy scopes, changed OCR adapter typing, and outgoing-history sensitive-asset checks pass.

Ten output-stage invocations still fail closed on persisted field-decision mismatch. All twelve claims require review; no output was produced. This safety behavior was retained, and this work does not claim end-to-end output readiness or production accuracy qualification.

The final run recorded 286.05 seconds summed across the 12 scans and overlapped regression activity. An earlier completed crop-mode iteration recorded 208.18 seconds. These are execution receipts, not a controlled performance comparison.

## Changed files

- `config/document_routing.yaml`
- `packages/document_routing/router.py`
- `packages/evidence_decision/adapters.py`
- `packages/settings.py`
- `packages/templates/cms1500_boxes.py`
- `tests/unit/cases/test_cms1500_template_first.py`
- `tests/unit/cases/test_standard_form_extraction_worker.py`
- `workers/cascade/instrumented_text_extractor.py`
- `workers/cascade/tesseract_adapter.py`
- `workers/document_preparation/preprocessing.py`
- `workers/page_detection/text_extraction.py`
- `workers/standard_form_extraction/consumer.py`
- `workers/standard_form_extraction/extractor.py`
