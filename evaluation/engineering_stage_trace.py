"""Value-free first-failure attribution for local engineering stage receipts.

This module never reads OCR or labels. Callers supply proven booleans; unknown
preconditions stop attribution rather than turning a mismatch into an OCR error.
"""
from __future__ import annotations

from collections.abc import Mapping

STAGES = (
    "FORM_IDENTITY", "PAGE_REGISTRATION", "CANONICAL_BOX_CONTAINS_VALUE",
    "DIRECT_RECOGNIZER_RECOVERS_VALUE", "FIELD_ASSEMBLY_SELECTS_VALUE",
    "NORMALIZATION_PRESERVES_VALUE", "FINAL_FIELD_OUTPUT_MATCHES_TRUTH",
)
ROOT_CAUSES = (
    "FORM_ROUTING", "PAGE_REGISTRATION", "CROP_GEOMETRY", "OCR_RECOGNITION",
    "FIELD_ASSEMBLY", "FIELD_MAPPING", "NORMALIZATION", "EXECUTION_FAILURE", "OTHER",
)
_CAUSE = dict(zip(STAGES, (
    "FORM_ROUTING", "PAGE_REGISTRATION", "CROP_GEOMETRY", "OCR_RECOGNITION",
    "FIELD_ASSEMBLY", "NORMALIZATION", "FIELD_MAPPING",
), strict=True))


def first_failure(stages: Mapping[str, bool | None], *,
                  execution_failure_at: str | None = None,
                  source_field_binding_verified: bool = True) -> dict:
    if set(stages) != set(STAGES):
        raise ValueError("STAGE_SET_INCOMPLETE")
    if any(value is not None and type(value) is not bool for value in stages.values()):
        raise ValueError("STAGE_RESULTS_MUST_BE_BOOLEAN_OR_UNKNOWN")
    if execution_failure_at is not None and execution_failure_at not in STAGES:
        raise ValueError("EXECUTION_STAGE_INVALID")
    for stage in STAGES:
        if stage == execution_failure_at:
            return {"first_stage": stage, "root_cause": "EXECUTION_FAILURE", "status": "FAIL"}
        value = stages[stage]
        if value is None:
            return {"first_stage": stage, "root_cause": "OTHER", "status": "UNVERIFIED"}
        if not value:
            cause = _CAUSE[stage]
            if stage == "CANONICAL_BOX_CONTAINS_VALUE" and not source_field_binding_verified:
                cause = "OTHER"
            return {"first_stage": stage, "root_cause": cause, "status": "FAIL"}
    return {"first_stage": None, "root_cause": None, "status": "PASS"}
