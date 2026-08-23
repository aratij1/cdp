"""Legacy evaluation analytics for HITL optimization.

This module is not a production field-disposition authority. Runtime code
must consume ``FieldDecision`` objects emitted by ``EvidenceDecisionService``.
The legacy ``decide`` function remains for historical evaluation reports and
route-migration analysis only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from packages.evidence_decision.contracts import FieldDecision, FieldDisposition


class HitlDisposition(StrEnum):
    ALREADY_AUTOMATED = "ALREADY_AUTOMATED"
    PROMOTED_REFERENCE_VERIFIED = "PROMOTED_REFERENCE_VERIFIED"
    PROMOTED_ACTIVE_ROUTE = "PROMOTED_ACTIVE_ROUTE"
    BLOCKED_REFERENCE_REQUIRED = "BLOCKED_REFERENCE_REQUIRED"
    BLOCKED_HOLDOUT_REQUIRED = "BLOCKED_HOLDOUT_REQUIRED"
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"
    BLOCKED_CONTRADICTION = "BLOCKED_CONTRADICTION"
    BLOCKED_LOW_CONFIDENCE = "BLOCKED_LOW_CONFIDENCE"
    BLOCKED_CROP_QUALITY = "BLOCKED_CROP_QUALITY"


@dataclass(frozen=True)
class HitlDecision:
    disposition: HitlDisposition
    automatically_acceptable: bool
    reason: str


@dataclass(frozen=True)
class CanonicalHITLSummary:
    field_name: str
    review_required: bool
    disposition: str
    reason_codes: tuple[str, ...]


class CanonicalHITLAuthority:
    """Read-only HITL projection of canonical field decisions."""

    _REVIEW = {
        FieldDisposition.ESCALATE,
        FieldDisposition.HUMAN_REVIEW_REQUIRED,
        FieldDisposition.INSUFFICIENT_EVIDENCE,
    }

    @classmethod
    def summarize(cls, decision: FieldDecision) -> CanonicalHITLSummary:
        return CanonicalHITLSummary(
            field_name=decision.field_name,
            review_required=decision.disposition in cls._REVIEW,
            disposition=decision.disposition.value,
            reason_codes=tuple(decision.reason_codes),
        )


def identity_key(prediction: dict[str, Any]) -> str:
    identity = prediction["field_identity"]
    return "|".join(str(identity.get(key) or "") for key in (
        "document_id", "page_number", "document_family", "service_line_number",
        "semantic_field",
    ))


def route_key(prediction: dict[str, Any]) -> str:
    identity = prediction["field_identity"]
    return f"{identity.get('document_family')}|{identity.get('semantic_field')}"


def _minimum_confidence(prediction: dict[str, Any], policy: dict[str, Any]) -> float:
    route_policy = policy["route_promotion"]
    route_thresholds = route_policy.get("minimum_confidence_by_route", {})
    field_thresholds = route_policy.get("minimum_confidence_by_field", {})
    field = str(prediction["field_identity"].get("semantic_field") or "")
    return float(route_thresholds.get(
        route_key(prediction),
        field_thresholds.get(field, route_policy.get("minimum_confidence", 0.0)),
    ))


def decide(
    prediction: dict[str, Any],
    policy: dict[str, Any],
    *,
    reference_decisions: dict[str, str],
    active_routes: set[str],
) -> HitlDecision:
    """Legacy evaluation-only migration analysis; never a runtime authority."""
    if not prediction.get("review_required", False):
        return HitlDecision(HitlDisposition.ALREADY_AUTOMATED, True, "existing automatic disposition")
    validations = set(prediction.get("validation_results") or [])
    reference = reference_decisions.get(identity_key(prediction))
    if reference in set(policy["reference_promotion"]["reject_decisions"]):
        return HitlDecision(HitlDisposition.BLOCKED_CONTRADICTION, False, reference)
    if reference == policy["reference_promotion"]["required_decision"]:
        return HitlDecision(
            HitlDisposition.PROMOTED_REFERENCE_VERIFIED,
            True,
            "authorized multi-attribute reference verification",
        )
    reason = (prediction.get("provenance") or {}).get("reason")
    field = prediction["field_identity"].get("semantic_field")
    if reason in policy["reference_required_reasons"] or field in policy["critical_identity_fields"]:
        return HitlDecision(
            HitlDisposition.BLOCKED_REFERENCE_REQUIRED,
            False,
            "authorized reference decision unavailable",
        )
    route = route_key(prediction)
    if route not in active_routes:
        return HitlDecision(
            HitlDisposition.BLOCKED_HOLDOUT_REQUIRED,
            False,
            f"field-family route is not ACTIVE: {route}",
        )
    confidence = float(prediction.get("confidence") or 0.0)
    minimum_confidence = _minimum_confidence(prediction, policy)
    if confidence < minimum_confidence:
        return HitlDecision(
            HitlDisposition.BLOCKED_LOW_CONFIDENCE,
            False,
            f"confidence {confidence:.3f} below route threshold {minimum_confidence:.3f}",
        )
    allowed_crop_quality = set(policy["route_promotion"].get("allowed_crop_quality", []))
    crop_quality = str(prediction.get("crop_quality") or "UNKNOWN")
    if allowed_crop_quality and crop_quality not in allowed_crop_quality:
        return HitlDecision(
            HitlDisposition.BLOCKED_CROP_QUALITY,
            False,
            f"crop quality is not eligible for automation: {crop_quality}",
        )
    required = set(policy["route_promotion"]["required_validation_results"])
    forbidden = set(policy["route_promotion"]["forbidden_validation_results"])
    if required.issubset(validations) and not validations.intersection(forbidden):
        return HitlDecision(
            HitlDisposition.PROMOTED_ACTIVE_ROUTE,
            True,
            "active field-family route with required independent validation",
        )
    return HitlDecision(
        HitlDisposition.BLOCKED_INSUFFICIENT_EVIDENCE,
        False,
        "active route lacks required validation evidence",
    )
