"""Machine-readable, evidence-only reasons for field review decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from packages.domain.enums import ReviewReasonCode

_FORM_LABELS = {"ADMISSION", "BIRTHDATE", "INSURED", "NAME", "PATIENT"}
_REFERENCE_FIELDS = {
    "patient_first",
    "patient_last",
    "patient_dob",
    "provider_npi",
    "federal_tax_id",
    "principal_diagnosis",
    "cpt_hcpcs",
    "member_id",
}


class PredictionEvidence(Protocol):
    raw_value: str | None
    normalized_value: str | None
    confidence: float | None
    validation_result: str
    accepted: bool
    metadata: dict[str, object]


@dataclass(frozen=True)
class ReviewReasonContext:
    form_type: str
    field_name: str
    critical: bool
    prediction: PredictionEvidence | None
    crop_evidence: dict[str, object] | None = None


def _candidate_values(prediction: PredictionEvidence) -> set[str]:
    return {
        str(item.get("value", "")).strip()
        for item in prediction.metadata.get("ocr_candidates", [])
        if str(item.get("value", "")).strip()
    }


def _candidate_engines(prediction: PredictionEvidence) -> set[str]:
    return {
        str(item.get("engine", "")).strip()
        for item in prediction.metadata.get("ocr_candidates", [])
        if str(item.get("engine", "")).strip()
    }


def classify_review_reasons(context: ReviewReasonContext) -> tuple[ReviewReasonCode, ...]:
    prediction = context.prediction
    crop = context.crop_evidence or {}
    reasons: set[ReviewReasonCode] = set()
    if context.form_type == "UNSTRUCTURED":
        reasons.add(ReviewReasonCode.UNSTRUCTURED_DOCUMENT)
    if prediction is None:
        reasons.add(ReviewReasonCode.NO_EVIDENCE)
        return tuple(sorted(reasons, key=str))

    value = (prediction.raw_value or prediction.normalized_value or "").strip()
    candidates = _candidate_values(prediction)
    engines = _candidate_engines(prediction)
    families = set(prediction.metadata.get("independent_families", []))
    if not value:
        reasons.add(ReviewReasonCode.NO_EVIDENCE)
        reasons.add(ReviewReasonCode.EMPTY_CROP)
    if len(candidates) > 1:
        reasons.add(ReviewReasonCode.OCR_DISAGREEMENT)
        reasons.add(ReviewReasonCode.MULTIPLE_PLAUSIBLE_VALUES)
    elif len(engines) > 1 and len(families) < 2:
        reasons.add(ReviewReasonCode.OCR_DISAGREEMENT)
    if prediction.confidence is not None and prediction.confidence < 0.80:
        reasons.add(ReviewReasonCode.LOW_OCR_CONFIDENCE)
    if context.critical and context.field_name in {"patient_first", "patient_last"}:
        reasons.add(ReviewReasonCode.CRITICAL_NAME_UNVERIFIED)
    if prediction.validation_result not in {
        "VALID",
        "VALID_INDEPENDENT_CONSENSUS",
    } and value:
        reasons.add(ReviewReasonCode.INVALID_FORMAT)
    upper_value = value.upper()
    if any(label in upper_value.split() for label in _FORM_LABELS):
        reasons.add(ReviewReasonCode.LABEL_CONTAMINATION)
    if context.field_name == "rel_code" and not prediction.accepted:
        reasons.add(ReviewReasonCode.CHECKBOX_AMBIGUOUS)
    if (
        "addr" in context.field_name
        or context.field_name.endswith(("_city", "_state", "_zip"))
    ) and not prediction.accepted:
        reasons.add(ReviewReasonCode.ADDRESS_AMBIGUOUS)
    if context.field_name in _REFERENCE_FIELDS and not prediction.metadata.get("reference_result"):
        reasons.add(ReviewReasonCode.NO_REFERENCE_MATCH)
    if prediction.metadata.get("reference_contradiction"):
        reasons.add(ReviewReasonCode.REFERENCE_CONTRADICTION)

    alignment = crop.get("alignment_score")
    local_accepted = crop.get("local_alignment_accepted")
    if isinstance(alignment, int | float) and alignment < 0.60:
        reasons.add(ReviewReasonCode.LOW_REGISTRATION_CONFIDENCE)
    if local_accepted is False:
        reasons.add(ReviewReasonCode.WRONG_CROP_SUSPECTED)
    if context.form_type == "UB04" and context.field_name.startswith("service_line"):
        reasons.add(ReviewReasonCode.TABLE_EXTRACTION_FAILURE)
    if not reasons:
        reasons.add(ReviewReasonCode.NO_EVIDENCE)
    return tuple(sorted(reasons, key=str))


def review_evidence_summary(prediction: PredictionEvidence | None) -> dict[str, object]:
    if prediction is None:
        return {"engines": [], "candidate_disagreement": False, "reference_available": False}
    return {
        "engines": sorted(_candidate_engines(prediction)),
        "candidate_disagreement": len(_candidate_values(prediction)) > 1,
        "reference_available": bool(prediction.metadata.get("reference_result")),
    }
