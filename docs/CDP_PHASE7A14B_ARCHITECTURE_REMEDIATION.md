# CDP Phase 7A.14B Architecture Remediation

The live standard-form worker now separates form identity from geometry authority. Fixed fields are OCRed only through `REGISTERED_FIXED`; incompatible templates, missing references, rejected registration, or invalid corners are diverted to `LAYOUT_STRUCTURED_EXTRACTOR` before field OCR. The former rescale-only fixed-ROI path and extraction-stage HITL events were removed.

Decision chain: form identity → compatibility → registration → ROI resolver → OCR candidates → validation/evidence decision → canonical HITL if unresolved.

```json
{
  "contract_version": "extraction-geometry-policy-v1",
  "modes": [
    "REGISTERED_FIXED",
    "ANCHOR_RELATIVE",
    "STRUCTURAL_LAYOUT",
    "SAFE_FALLBACK",
    "UNAVAILABLE"
  ],
  "standard_request_mode_required": true,
  "form_identity_separate_from_registration": true,
  "fixed_requires_compatible_template": true,
  "fixed_requires_accepted_registration": true,
  "fixed_requires_valid_transformed_geometry": true,
  "registration_failure_fixed_roi_calls": 0,
  "rescale_only_fixed_extraction_enabled": false,
  "safe_layout_fallback": "LAYOUT_STRUCTURED_EXTRACTOR",
  "roi_resolver_version": "roi-resolver-v1",
  "runtime_evaluation_resolver_shared": true,
  "anchor_relative_contract": "FIELD_SPECIFIC_NORMALIZED_OFFSETS_FROM_OBSERVED_ANCHOR"
}
```
