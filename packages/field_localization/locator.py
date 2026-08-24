from __future__ import annotations

import re
from difflib import SequenceMatcher
from hashlib import sha256

from packages.page_observation import ObservationToken, PageObservation
from packages.roi_resolution import ROIResolutionMode

from .contracts import (
    FieldDefinition,
    FieldLocationEvidence,
    LocalizationCandidate,
    LocalizationStage,
    PageZone,
)
from .scoring import LocalizationScoringPolicy, semantic_confidence


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


def _hash(page_id: str, field: str, source: str, bbox: tuple[int, int, int, int]) -> str:
    raw = f"{page_id}|{field}|{source}|{','.join(str(item) for item in bbox)}"
    return sha256(raw.encode()).hexdigest()


def _clip(box: tuple[float, float, float, float], page: PageObservation):
    return (
        max(0, round(box[0])), max(0, round(box[1])),
        min(page.width, round(box[2])), min(page.height, round(box[3])),
    )


def _overlap_y(left: ObservationToken, right: ObservationToken) -> float:
    overlap = max(0.0, min(left.bbox[3], right.bbox[3]) - max(left.bbox[1], right.bbox[1]))
    height = min(left.bbox[3] - left.bbox[1], right.bbox[3] - right.bbox[1])
    return overlap / height if height else 0.0


class FieldLocator:
    """Truth-blind, multi-candidate anchor-relative field localization."""

    version = "field-locator-v3-multi-candidate"

    def __init__(self, policy: LocalizationScoringPolicy | None = None) -> None:
        self.policy = policy or LocalizationScoringPolicy.load()

    def locate(self, observation: PageObservation, definition: FieldDefinition) -> FieldLocationEvidence:
        anchor_matches = self._anchors(observation, definition)
        if not anchor_matches:
            return FieldLocationEvidence(
                field_name=definition.field_name, form_family=definition.form_family,
                confidence=0, page_id=observation.page_id,
                stage=LocalizationStage.UNRESOLVED,
                reason_codes=("FIELD_ANCHOR_NOT_FOUND",), locator_version=self.version,
            )

        anchor_score, anchor, alias = anchor_matches[0]
        candidates = self._candidates(observation, definition, anchor, anchor_score)
        if not candidates:
            return FieldLocationEvidence(
                field_name=definition.field_name, form_family=definition.form_family,
                confidence=anchor_score, anchor_ids=(anchor.token_id,),
                page_id=observation.page_id, stage=LocalizationStage.ANCHOR_FOUND,
                anchor_text=anchor.text, anchor_bbox=tuple(round(item) for item in anchor.bbox),
                anchor_confidence=anchor_score,
                reason_codes=("BOUNDED_ALIAS_MATCH", "REGION_CANDIDATES_EMPTY"),
                locator_version=self.version,
            )

        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        selected = ranked[0]
        fallback = next((item for item in ranked
                         if item.region_source == "ANCHOR_RELATIVE_CONTRACT"), None)
        if (selected.semantic_confidence or 0) < .50 and fallback is not None:
            selected = fallback
            ranked = [selected, *(item for item in ranked if item is not selected)]
        competing = next((item for item in ranked[1:]
                          if _normalized(item.observed_text or "")
                          != _normalized(selected.observed_text or "")
                          and not (set(item.token_ids) & set(selected.token_ids))
                          and item.region_source.split("_TOKEN")[0].split("_LINE")[0]
                          == selected.region_source.split("_TOKEN")[0].split("_LINE")[0]
                          and (item.semantic_confidence or 0) >= .75), None)
        reasons = [
            "BOUNDED_ALIAS_MATCH", "MULTI_CANDIDATE_REGION_RANKING",
            "ANCHOR_RELATIVE_GEOMETRY_VALIDATED", "OBSERVED_VALUE_SPAN_GEOMETRY",
            "NEIGHBOR_BOUNDARY_VALIDATED", f"CANDIDATE_SOURCE_{selected.region_source}",
        ]
        wrong_crop = False
        contract_region = selected.region_source == "ANCHOR_RELATIVE_CONTRACT"
        if not selected.observed_text and not contract_region:
            reasons.append("WRONG_CROP_EMPTY")
            wrong_crop = True
        if (selected.semantic_confidence or 0) < .20 and not contract_region:
            reasons.append("WRONG_CROP_SEMANTIC_MISMATCH")
            wrong_crop = True
        if selected.geometry_confidence < .50:
            reasons.append("WRONG_CROP_GEOMETRY")
            wrong_crop = True
        if "LABEL_ONLY" in selected.reason_codes:
            reasons.append("WRONG_CROP_LABEL_ONLY")
            wrong_crop = True
        ambiguity_margin = (
            self.policy.ambiguity_margin
            if definition.datatype in {
                "DATE", "PERSON_NAME", "PERSON_OR_ORGANIZATION"
            }
            else .005
        )
        if competing and selected.score - competing.score < ambiguity_margin:
            reasons.extend(("MULTIPLE_COMPETING_FIELD_VALUES", "WRONG_CROP_NEIGHBOR_FIELD"))
            wrong_crop = True
        if selected.score < self.policy.minimum_region_score and not contract_region:
            reasons.append("LOW_REGION_SCORE")
            wrong_crop = True

        stage = (LocalizationStage.REGION_GEOMETRY_VALIDATED if contract_region else
                 LocalizationStage.VALUE_SEMANTICALLY_VALIDATED
                 if not wrong_crop and (selected.semantic_confidence or 0) >= .50
                 else LocalizationStage.VALUE_SPAN_DETECTED)
        confidence = (min(anchor_score, selected.geometry_confidence)
                      if contract_region else
                      min(selected.score, anchor_score, selected.geometry_confidence,
                          selected.span_confidence or 0))
        if contract_region:
            reasons = [
                "BOUNDED_ALIAS_MATCH", "MULTI_CANDIDATE_REGION_RANKING",
                "ANCHOR_RELATIVE_GEOMETRY_VALIDATED", "FIELD_SPECIFIC_SPATIAL_CONTRACT",
                "CANDIDATE_SOURCE_ANCHOR_RELATIVE_CONTRACT",
                "OCR_REQUIRED_TO_VALIDATE_REGION",
            ]
        return FieldLocationEvidence(
            field_name=definition.field_name, form_family=definition.form_family,
            bbox=selected.bbox, method=ROIResolutionMode.ANCHOR_RELATIVE,
            confidence=confidence, anchor_ids=(anchor.token_id,),
            reason_codes=tuple(reasons), locator_version=self.version,
            page_id=observation.page_id, stage=stage, anchor_text=alias,
            anchor_bbox=tuple(round(item) for item in anchor.bbox),
            anchor_confidence=anchor_score, region_source=selected.region_source,
            geometry_confidence=selected.geometry_confidence,
            span_confidence=selected.span_confidence,
            semantic_confidence=selected.semantic_confidence,
            candidate_region_hash=selected.candidate_region_hash,
            selected_candidate_id=selected.candidate_id, candidates=tuple(ranked),
            wrong_crop_suspected=wrong_crop,
        )

    def _anchors(self, observation: PageObservation, definition: FieldDefinition):
        negatives = {_normalized(value) for value in definition.negative_labels}
        matches: list[tuple[float, ObservationToken, str]] = []
        for token in observation.ocr_tokens:
            text = _normalized(token.text)
            if not text or any(negative and negative in text for negative in negatives):
                continue
            for alias in definition.aliases:
                normalized_alias = _normalized(alias)
                similarity = max(
                    SequenceMatcher(None, text, normalized_alias).ratio(),
                    SequenceMatcher(None, text[:len(normalized_alias)], normalized_alias).ratio(),
                )
                score = similarity * (0.8 + 0.2 * _zone_score(
                    token, observation, definition.page_zone
                )) * token.confidence
                if similarity >= definition.fuzzy_threshold and token.confidence >= .45:
                    matches.append((score, token, alias))
        return sorted(matches, key=lambda item: item[0], reverse=True)

    def _candidates(self, observation: PageObservation, definition: FieldDefinition,
                    anchor: ObservationToken, anchor_score: float) -> list[LocalizationCandidate]:
        aliases = {_normalized(item) for item in (*definition.aliases, *definition.negative_labels)}
        relation = definition.relationships[0]
        nearby: list[tuple[ObservationToken, float, str]] = []
        for token in observation.ocr_tokens:
            if token.token_id == anchor.token_id or self._is_label(token.text, aliases, definition):
                continue
            below = self._geometry(token, anchor, observation, "below")
            right = self._geometry(token, anchor, observation, "right_of")
            geometry, source = max((below, "ANCHOR_BELOW"), (right, "ANCHOR_RIGHT"))
            if geometry > 0:
                nearby.append((token, geometry, source))

        groups: list[tuple[list[ObservationToken], float, str]] = []
        textual = definition.datatype in {
            "PERSON_NAME", "PERSON_OR_ORGANIZATION", "ADDRESS", "TEXT"
        }
        if textual:
            by_line: dict[int, list[tuple[ObservationToken, float, str]]] = {}
            for item in nearby:
                by_line.setdefault(item[0].line_index, []).append(item)
            for line in by_line.values():
                ordered = sorted(line, key=lambda item: item[0].bbox[0])
                runs: list[list[tuple[ObservationToken, float, str]]] = []
                for item in ordered:
                    if not runs:
                        runs.append([item])
                        continue
                    prior = runs[-1][-1][0]
                    gap = item[0].bbox[0] - prior.bbox[2]
                    height = max(1.0, prior.bbox[3] - prior.bbox[1])
                    if gap <= max(3.5 * height, .035 * observation.width):
                        runs[-1].append(item)
                    else:
                        runs.append([item])
                for run in runs:
                    limited = run[:6]
                    direction = max(limited, key=lambda item: item[1])[2]
                    groups.append(([item[0] for item in limited],
                                   sum(item[1] for item in limited) / len(limited),
                                   f"{direction}_LINE_SPAN"))
        groups.extend(([token], geometry, f"{source}_TOKEN_SPAN")
                      for token, geometry, source in nearby)

        candidates: list[LocalizationCandidate] = []
        seen: set[tuple[int, int, int, int]] = set()
        for tokens, geometry, source in groups:
            box = self._padded_bbox(tokens, observation, definition.datatype)
            if box in seen or box[2] <= box[0] or box[3] <= box[1]:
                continue
            seen.add(box)
            observed = " ".join(token.text for token in tokens).strip()
            span = sum(token.confidence for token in tokens) / len(tokens)
            semantic = semantic_confidence(
                definition.datatype, observed, definition.field_name
            )
            score = self.policy.score(definition.form_family, definition.field_name,
                                      anchor=anchor_score, geometry=geometry, span=span,
                                      semantic=semantic)
            region_hash = _hash(observation.page_id, definition.field_name, source, box)
            candidates.append(LocalizationCandidate(
                candidate_id=region_hash[:24], bbox=box, region_source=source,
                token_ids=tuple(token.token_id for token in tokens), observed_text=observed,
                geometry_confidence=geometry, span_confidence=span,
                semantic_confidence=semantic, score=score,
                candidate_region_hash=region_hash,
                reason_codes=("TOKEN_DERIVED_REGION",),
            ))

        ax0, ay0, _, _ = anchor.bbox
        fallback = _clip((
            ax0 + relation.x0_offset * observation.width,
            ay0 + relation.y0_offset * observation.height,
            ax0 + relation.x1_offset * observation.width,
            ay0 + relation.y1_offset * observation.height,
        ), observation)
        if fallback[2] > fallback[0] and fallback[3] > fallback[1] and fallback not in seen:
            score = self.policy.score(definition.form_family, definition.field_name,
                                      anchor=anchor_score, geometry=.65, span=0, semantic=0)
            region_hash = _hash(observation.page_id, definition.field_name,
                                "ANCHOR_RELATIVE_CONTRACT", fallback)
            candidates.append(LocalizationCandidate(
                candidate_id=region_hash[:24], bbox=fallback,
                region_source="ANCHOR_RELATIVE_CONTRACT", geometry_confidence=.65,
                span_confidence=0, semantic_confidence=0, score=score,
                candidate_region_hash=region_hash,
                reason_codes=("FIELD_SPECIFIC_SPATIAL_CONTRACT",),
            ))
        return candidates

    @staticmethod
    def _is_label(text: str, aliases: set[str], definition: FieldDefinition) -> bool:
        compact = _normalized(text).replace(" ", "")
        if not compact:
            return True
        if any(alias.replace(" ", "") in compact or compact in alias.replace(" ", "")
               for alias in aliases if len(alias.replace(" ", "")) >= 3):
            return True
        return _normalized(text) in {_normalized(name) for name in definition.neighbor_fields}

    @staticmethod
    def _geometry(token: ObservationToken, anchor: ObservationToken,
                  page: PageObservation, relation: str) -> float:
        tcx = (token.bbox[0] + token.bbox[2]) / 2
        tcy = (token.bbox[1] + token.bbox[3]) / 2
        acx = (anchor.bbox[0] + anchor.bbox[2]) / 2
        acy = (anchor.bbox[1] + anchor.bbox[3]) / 2
        if relation == "right_of":
            dx = tcx - anchor.bbox[2]
            dy = abs(tcy - acy)
            if dx < -.015 * page.width or dx > .36 * page.width or dy > .055 * page.height:
                return 0.0
            overlap = _overlap_y(token, anchor)
            return max(.05, min(1.0, .65 + .25 * overlap
                                - .35 * max(0, dx) / (.36 * page.width)))
        dy = token.bbox[1] - anchor.bbox[3]
        dx = abs(tcx - acx)
        if dy < -.008 * page.height or dy > .10 * page.height or dx > .46 * page.width:
            return 0.0
        return max(.05, min(1.0, .95 - .50 * max(0, dy) / (.10 * page.height)
                            - .20 * dx / (.46 * page.width)))

    @staticmethod
    def _padded_bbox(tokens: list[ObservationToken], page: PageObservation,
                     datatype: str) -> tuple[int, int, int, int]:
        height = max(token.bbox[3] - token.bbox[1] for token in tokens)
        left = max(.006 * page.width, .55 * height)
        # OCR word boxes commonly terminate before the rendered glyph/field
        # boundary on skewed renderer-C pages. The padding remains bounded to
        # 6.5% of page width and never influences semantic acceptance.
        right_factor = 3.5 if datatype in {"PERSON_NAME", "PERSON_OR_ORGANIZATION"} else 2.8
        minimum_right = (.09 if datatype in {
            "PERSON_NAME", "PERSON_OR_ORGANIZATION"
        } else .065) * page.width
        right = max(minimum_right, right_factor * height)
        vertical = max(.010 * page.height, .60 * height)
        return _clip((
            min(token.bbox[0] for token in tokens) - left,
            min(token.bbox[1] for token in tokens) - vertical,
            max(token.bbox[2] for token in tokens) + right,
            max(token.bbox[3] for token in tokens) + vertical,
        ), page)
