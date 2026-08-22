# CDP reference matching report

Status date: 2026-08-22. Phase 3 is implemented but remains a governed candidate until measured on a representative labeled dataset.

## Implemented controls

- Member matching uses multiple independent attributes: member ID, DOB, name and ZIP/address. A fuzzy name alone cannot verify identity.
- Provider matching requires an exact, checksum-valid NPI from an active authorized record.
- CPT, HCPCS and ICD-10 references require a versioned snapshot timestamp and checksum; syntax alone is not authoritative verification.
- Reference sources support local fixtures, checksum-protected snapshots, CSV/JSON/XLSX batches, REST APIs and read-only database queries through a common lookup contract.
- Sources must be authorized, independent truth with non-circular lineage. Evaluation truth and unreviewed CDP output are prohibited sources.
- Corrections preserve raw, normalized, reference-candidate, corrected and final values plus matching/conflicting attributes, source, version and confidence.
- A verified reference match now produces the distinct `REFERENCE_CONFIRMED` reconciliation decision with source/version evidence.
- A verified reference that contradicts the leading OCR candidate now forces `REVIEW` with `REFERENCE_CONTRADICTION`, even when two OCR engines agree and deterministic syntax/checksum passes.

## Safety policy

Reference evidence is usable for automated acceptance only when provider authorization, lineage, record status, dataset version, multi-attribute matching and field-specific rules all pass. Multiple records, unavailable sources, provider errors, missing code-snapshot provenance and contradictions fail closed. OCR-like character substitutions are never performed silently.

## Current measured baseline

Overall accuracy 72.13%; CMS-1500 87.33%; UB-04 75.93%; critical-field accuracy 65.56%; false accepts 0; STP 0%; review rate 76.67%; perfect claims 20%. Phase 3 has no newly measured accuracy, STP, review, cost or latency delta yet.

## Promotion requirement

Run the governed experiment ledger against representative, independently sourced member/provider/code snapshots. Report match precision, correction precision, reference coverage, former-review fields safely automated, new false accepts, critical false accepts, latency and cost. Promotion requires no critical false-accept regression and no critical-accuracy regression.
