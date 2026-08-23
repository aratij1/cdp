from __future__ import annotations

import re
from difflib import SequenceMatcher

from packages.page_observation import ObservationToken, PageObservation
from packages.roi_resolution import ROIResolutionMode

from .contracts import FieldDefinition, FieldLocationEvidence, PageZone


def _normalized(text: str) -> str:
    return re.sub(r"[^A-Z0-9 ]", "", text.upper()).replace("1", "I").strip()


def _zone_score(token: ObservationToken, page: PageObservation, zone: PageZone) -> float:
    if zone == PageZone.ANY:
        return 1.0
    cx = (token.bbox[0] + token.bbox[2]) / (2 * page.width)
    cy = (token.bbox[1] + token.bbox[3]) / (2 * page.height)
    vertical = "UPPER" if cy < .4 else "LOWER" if cy > .62 else "MIDDLE"
    horizontal = "LEFT" if cx < .4 else "RIGHT" if cx > .62 else "MIDDLE"
    expected = zone.value.split("_")
    return 1.0 if vertical in expected and horizontal in expected else .45


class FieldLocator:
    version = "field-locator-v1"

    def locate(self, observation: PageObservation, definition: FieldDefinition) -> FieldLocationEvidence:
        negatives = {_normalized(value) for value in definition.negative_labels}
        candidates: list[tuple[float, ObservationToken, str]] = []
        for token in observation.ocr_tokens:
            text = _normalized(token.text)
            if not text or any(negative in text for negative in negatives):
                continue
            for alias in definition.aliases:
                normalized_alias = _normalized(alias)
                # Matching is bounded by field aliases, the expected page zone,
                # and a minimum token confidence; it is never corpus-wide fuzzy search.
                similarity = max(
                    SequenceMatcher(None, text, normalized_alias).ratio(),
                    SequenceMatcher(None, text[: len(normalized_alias)], normalized_alias).ratio(),
                )
                zone = _zone_score(token, observation, definition.page_zone)
                score = similarity * (0.8 + 0.2 * zone) * token.confidence
                if similarity >= definition.fuzzy_threshold and token.confidence >= .45:
                    candidates.append((score, token, alias))
        if not candidates:
            return FieldLocationEvidence(
                field_name=definition.field_name, form_family=definition.form_family,
                confidence=0, reason_codes=("FIELD_ANCHOR_NOT_FOUND",),
            )
        score, anchor, _ = max(candidates, key=lambda item: item[0])
        # Prefer observed value-token geometry over a broad configured offset.
        # A value is the nearest non-label token immediately below the anchor
        # and within the same local field neighborhood.
        local = [token for token in observation.ocr_tokens
                 if token.token_id != anchor.token_id
                 and anchor.bbox[3] + .002*observation.height <= token.bbox[1]
                 <= anchor.bbox[3] + .075*observation.height
                 and anchor.bbox[0] - .02*observation.width <= token.bbox[0]
                 <= anchor.bbox[0] + max(.28*observation.width,
                                        2.5*(anchor.bbox[2]-anchor.bbox[0]))
                 and not any(SequenceMatcher(None, _normalized(token.text), _normalized(alias)).ratio()
                             >= definition.fuzzy_threshold for alias in definition.aliases)]
        if local:
            first_y = min(token.bbox[1] for token in local)
            row_candidates = [token for token in local
                              if abs(token.bbox[1] - first_y) <= .018*observation.height]
            # Adjacent fields commonly share the same baseline.  The value
            # belonging to this label is the token whose left edge is nearest
            # the label's left edge, not every token on that page row.
            nearest = min(row_candidates, key=lambda token: abs(token.bbox[0]-anchor.bbox[0]))
            row = [nearest]
            pad_x, pad_y = .004*observation.width, .004*observation.height
            observed_box = (
                round(min(token.bbox[0] for token in row)-pad_x),
                round(min(token.bbox[1] for token in row)-pad_y),
                round(max(token.bbox[2] for token in row)+pad_x),
                round(max(token.bbox[3] for token in row)+pad_y),
            )
            clipped = (max(0, observed_box[0]), max(0, observed_box[1]),
                       min(observation.width, observed_box[2]),
                       min(observation.height, observed_box[3]))
            return FieldLocationEvidence(
                field_name=definition.field_name, form_family=definition.form_family,
                bbox=clipped, method=ROIResolutionMode.ANCHOR_RELATIVE,
                confidence=min(1, score), anchor_ids=(anchor.token_id,),
                reason_codes=("BOUNDED_ALIAS_MATCH", "OBSERVED_VALUE_TOKEN_GEOMETRY"),
            )
        relation = definition.relationships[0]
        ax0, ay0, _, _ = anchor.bbox
        box = (
            round(ax0 + relation.x0_offset * observation.width),
            round(ay0 + relation.y0_offset * observation.height),
            round(ax0 + relation.x1_offset * observation.width),
            round(ay0 + relation.y1_offset * observation.height),
        )
        clipped = (max(0, box[0]), max(0, box[1]), min(observation.width, box[2]),
                   min(observation.height, box[3]))
        if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
            return FieldLocationEvidence(
                field_name=definition.field_name, form_family=definition.form_family,
                confidence=score, anchor_ids=(anchor.token_id,),
                reason_codes=("ANCHOR_RELATIVE_BOX_OUT_OF_BOUNDS",),
            )
        return FieldLocationEvidence(
            field_name=definition.field_name, form_family=definition.form_family,
            bbox=clipped, method=ROIResolutionMode.ANCHOR_RELATIVE,
            confidence=min(1, score), anchor_ids=(anchor.token_id,),
            reason_codes=("BOUNDED_ALIAS_MATCH", "FIELD_SPECIFIC_SPATIAL_CONTRACT"),
        )
