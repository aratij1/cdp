# CDP Phase 5 — Field-Specific Evidence Policy

## Decision

**NEEDS_MORE_DATA.** Configurable field-specific evidence gates are active in both the evidence reconciler and the live OCR cascade. They preserve zero-false-accept behavior, but an authorized reference corpus is still required to convert the newly protected reviews into safe accepts.

## Implemented

- Versioned YAML policy selected by document family, field name, and criticality.
- Explicit evidence alternatives expressed as machine-readable signal conjunctions rather than a single global confidence threshold.
- Policy failures return `FIELD_EVIDENCE_POLICY_NOT_SATISFIED` or `field_evidence_policy_not_satisfied` with missing evidence alternatives.
- Low calibrated confidence escalates for additional evidence before final review.
- Unverified reference values no longer contribute reference score or acceptance evidence in the live cascade.

Current protected policies include:

| Field class | Required acceptance evidence |
|---|---|
| NPI | Independent OCR agreement plus checksum, or governed provider reference match |
| Member ID | Independent OCR plus reference, or reference plus DOB and name matches |
| DOB | Independent OCR plus member reference |
| Patient/provider name | Independent OCR plus identity reference evidence |
| CPT/HCPCS | Independent OCR plus versioned code-reference validation, or governed exact reference match |
| Total charge | Independent OCR plus service-line financial reconciliation |

Generic C0–C3 defaults remain available for fields without an override. Document-family rules take precedence over wildcard rules, which take precedence over criticality defaults.

## Runtime integration

The live `FieldCascade` now passes the document family into reconciliation. Protected fields do not inherit generic two-engine acceptance. Until checksum, authoritative-reference, code-snapshot, or financial-reconciliation signals are explicitly supplied, those fields fail closed to review.

## Results

- Focused and architecture tests: 47 passed.
- Full regression suite: 578 passed, 5 skipped, and the one previously known frozen-manifest hash failure.
- Static checks: passed.
- Safe review reduction: 0 / 262 = 0%.
- Review cases removed: 0.
- False accepts introduced: 0.
- Added compute/cloud cost and latency: 0.
- Accuracy and review-rate deltas: 0 percentage points; historical predictions were not reclassified using unavailable authoritative evidence.

## Limitations and next gate

- The policy is intentionally stricter than the legacy cascade for names, NPI, member IDs, codes, and total charge.
- Reference-dependent alternatives cannot pass until approved Phase 4 data sources are configured.
- Financial acceptance requires a service-line reconciliation signal that must come from validated claim arithmetic, not OCR confidence.
- Policy impact must be calibrated on development data and then verified on a new untouched holdout.

The next ordered phase is confidence calibration. Calibration may control escalation thresholds, but it must not bypass any field-specific evidence requirement.
