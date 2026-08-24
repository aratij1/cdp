"""Truth-blind field-region ownership and conflict classification."""

from __future__ import annotations

import re
from enum import StrEnum

from packages.page_observation import ObservationToken, PageObservation

from .contracts import FieldDefinition, LocalizationCandidate
from .scoring import type_compatibility


class RegionOwnership(StrEnum):
    REGION_OWNED = "REGION_OWNED"
    REGION_AMBIGUOUS = "REGION_AMBIGUOUS"
    WRONG_NEIGHBOR = "WRONG_NEIGHBOR"
    MULTI_FIELD_CROP = "MULTI_FIELD_CROP"
    LABEL_CONTAMINATED = "LABEL_CONTAMINATED"
    UNKNOWN = "UNKNOWN"


def _normalized(value: str) -> str:
    return re.sub(r"[^A-Z0-9 ]", "", value.upper()).strip()


def _overlaps(box: tuple[int, int, int, int], token: ObservationToken) -> bool:
    center_x = (token.bbox[0] + token.bbox[2]) / 2
    center_y = (token.bbox[1] + token.bbox[3]) / 2
    return box[0] <= center_x <= box[2] and box[1] <= center_y <= box[3]


class FieldRegionConflictDetector:
    """Classify ownership without consulting truth or downstream validators."""

    version = "field-region-conflict-v1"

    def classify(
        self,
        observation: PageObservation,
        definition: FieldDefinition,
        selected: LocalizationCandidate,
        competing: LocalizationCandidate | None = None,
        *,
        ambiguity_margin: float = 0.025,
    ) -> tuple[RegionOwnership, float, tuple[str, ...]]:
        if selected.region_source == "ANCHOR_RELATIVE_CONTRACT" and not selected.token_ids:
            return RegionOwnership.UNKNOWN, 0.35, ("OWNERSHIP_REQUIRES_OCR",)

        inside = [token for token in observation.ocr_tokens if _overlaps(selected.bbox, token)]
        negatives = {_normalized(item) for item in definition.negative_labels}
        neighbor_names = {_normalized(item.replace("_", " ")) for item in definition.neighbor_fields}
        own_aliases = {_normalized(item) for item in definition.aliases}
        foreign_labels = []
        own_labels = []
        for token in inside:
            text = _normalized(token.text)
            if any(label and (label in text or text in label) for label in own_aliases):
                own_labels.append(token.token_id)
            if any(label and (label in text or text in label)
                   for label in negatives | neighbor_names):
                foreign_labels.append(token.token_id)
        if foreign_labels:
            return RegionOwnership.WRONG_NEIGHBOR, 0.98, (
                "DECLARED_NEIGHBOR_LABEL_IN_REGION", *foreign_labels,
            )
        if own_labels:
            return RegionOwnership.LABEL_CONTAMINATED, 0.96, (
                "OWN_FIELD_LABEL_IN_VALUE_REGION", *own_labels,
            )
        selected_ids = set(selected.token_ids)
        extra_values = [
            token for token in inside
            if token.token_id not in selected_ids
            and type_compatibility(
                definition.datatype, token.text, definition.field_name
            ) >= .50
        ]
        if extra_values:
            return RegionOwnership.MULTI_FIELD_CROP, 0.94, (
                "MULTIPLE_TYPE_COMPATIBLE_SPANS_IN_REGION",
                *(token.token_id for token in extra_values),
            )
        if competing is not None and selected.score - competing.score < ambiguity_margin:
            return RegionOwnership.REGION_AMBIGUOUS, 0.90, (
                "COMPETING_DISJOINT_VALUE_REGIONS", competing.candidate_id,
            )
        if not selected.token_ids or not (selected.observed_text or "").strip():
            return RegionOwnership.UNKNOWN, 0.25, ("NO_OBSERVED_VALUE_SPAN",)
        if selected.geometry_confidence < 0.50:
            return RegionOwnership.UNKNOWN, 0.40, ("WEAK_RELATIONSHIP_GEOMETRY",)
        confidence = min(
            0.99,
            0.50 + 0.25 * selected.geometry_confidence
            + 0.15 * (selected.span_confidence or 0)
            + 0.10 * (selected.cross_field_confidence or 0),
        )
        reasons = [
            "DECLARED_RELATIONSHIP_SATISFIED",
            "NO_DECLARED_NEIGHBOR_LABEL_IN_REGION",
        ]
        if (selected.semantic_confidence or 0) < 0.20:
            reasons.append("TYPE_COMPATIBILITY_WEAK_OWNERSHIP_GEOMETRY_STRONG")
            confidence = min(confidence, .72)
        return RegionOwnership.REGION_OWNED, confidence, tuple(reasons)


WRONG_OWNERSHIP_OUTCOMES = frozenset({
    RegionOwnership.REGION_AMBIGUOUS,
    RegionOwnership.WRONG_NEIGHBOR,
    RegionOwnership.MULTI_FIELD_CROP,
    RegionOwnership.LABEL_CONTAMINATED,
})
