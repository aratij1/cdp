"""Explicit rule-based observation dependency classification."""

from __future__ import annotations

from packages.evidence_dependency.models import DependencyRelation, EvidenceDependencyResult
from packages.ocr.provenance import EvidenceProvenance


def _same(left: str | None, right: str | None) -> bool | None:
    return None if not left or not right else left == right


def _overlap(left, right) -> float | None:
    if left is None or right is None:
        return None
    lx0, ly0, lx1, ly1 = left.normalized()
    rx0, ry0, rx1, ry1 = right.normalized()
    area = max(0.0, min(lx1, rx1) - max(lx0, rx0)) * max(
        0.0, min(ly1, ry1) - max(ly0, ry0)
    )
    smallest = min(max(0.0, lx1 - lx0) * max(0.0, ly1 - ly0),
                   max(0.0, rx1 - rx0) * max(0.0, ry1 - ry0))
    return area / smallest if smallest else 0.0


class EvidenceDependencyService:
    """Classify lineage without treating engine diversity as decisive."""

    def classify(
        self,
        left: EvidenceProvenance | None,
        right: EvidenceProvenance | None,
    ) -> EvidenceDependencyResult:
        if left is None or right is None:
            return EvidenceDependencyResult(
                relation=DependencyRelation.UNKNOWN,
                reasons=("PROVENANCE_MISSING",),
                confidence=1.0,
            )

        dimensions: dict[str, bool | float | str | None] = {
            "same_original_page": _same(left.page_sha256, right.page_sha256),
            "same_page_representation": _same(
                left.source_representation_id, right.source_representation_id
            ),
            "same_observation": _same(left.observation_id, right.observation_id),
            "same_crop_hash": _same(left.crop_sha256, right.crop_sha256),
            "crop_overlap": _overlap(left.bbox, right.bbox),
            "same_localization_id": _same(left.localization_id, right.localization_id),
            "same_localization_algorithm": _same(
                left.localization_method, right.localization_method
            ),
            "same_preprocessing": _same(
                left.preprocessing_profile, right.preprocessing_profile
            ),
            "same_engine_family": _same(left.engine_family, right.engine_family),
            "same_model_family": _same(left.model_family, right.model_family),
            "same_registration_transform": _same(
                left.registration_transform_id, right.registration_transform_id
            ),
            "derived_lineage": bool(
                left.parent_candidate_id
                and left.parent_candidate_id
                in {right.source_candidate_id, right.parent_candidate_id}
            ) or bool(
                right.parent_candidate_id
                and right.parent_candidate_id
                in {left.source_candidate_id, left.parent_candidate_id}
            ),
        }
        overlap = dimensions["crop_overlap"]
        shared_pixels = dimensions["same_crop_hash"] is True or (
            isinstance(overlap, float) and overlap >= 0.90
        )
        shared_decision = (
            dimensions["same_localization_id"] is True
            or dimensions["same_observation"] is True
        )
        if dimensions["derived_lineage"] or (shared_pixels and shared_decision):
            reasons = ["DERIVED_CANDIDATE_LINEAGE"] if dimensions["derived_lineage"] else []
            if shared_pixels:
                reasons.append("SHARED_CROP_PIXELS")
            if shared_decision:
                reasons.append("SHARED_LOCALIZATION_OR_OBSERVATION")
            return EvidenceDependencyResult(
                relation=DependencyRelation.CORRELATED,
                reasons=tuple(reasons),
                dependency_dimensions=dimensions,
                confidence=0.99,
            )

        required = (
            left.source_representation_id,
            right.source_representation_id,
            left.crop_sha256,
            right.crop_sha256,
            left.localization_id,
            right.localization_id,
            left.preprocessing_profile,
            right.preprocessing_profile,
            left.engine_family,
            right.engine_family,
        )
        if any(value in (None, "") for value in required):
            return EvidenceDependencyResult(
                relation=DependencyRelation.UNKNOWN,
                reasons=("INSUFFICIENT_LINEAGE_DIMENSIONS",),
                dependency_dimensions=dimensions,
                confidence=0.95,
            )

        independent_dimensions = (
            dimensions["same_page_representation"] is False,
            dimensions["same_crop_hash"] is False,
            dimensions["same_localization_id"] is False,
            dimensions["same_preprocessing"] is False,
            dimensions["same_engine_family"] is False,
        )
        if all(independent_dimensions) and not (
            isinstance(overlap, float) and overlap >= 0.50
        ):
            return EvidenceDependencyResult(
                relation=DependencyRelation.INDEPENDENT,
                reasons=("INDEPENDENT_REPRESENTATION_CROP_LOCALIZATION_PREPROCESSING_ENGINE",),
                dependency_dimensions=dimensions,
                confidence=0.90,
            )
        return EvidenceDependencyResult(
            relation=DependencyRelation.PARTIALLY_INDEPENDENT,
            reasons=("MIXED_SHARED_AND_DISTINCT_LINEAGE",),
            dependency_dimensions=dimensions,
            confidence=0.80,
        )
