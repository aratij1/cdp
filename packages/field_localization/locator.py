from __future__ import annotations

import re
from difflib import SequenceMatcher
from hashlib import sha256

from packages.page_observation import ObservationToken, PageObservation
from packages.roi_resolution import ROIResolutionMode

from .conflict import WRONG_OWNERSHIP_OUTCOMES, FieldRegionConflictDetector
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

    version = "field-locator-v4-owned-bounded-region"

    def __init__(self, policy: LocalizationScoringPolicy | None = None) -> None:
        self.policy = policy or LocalizationScoringPolicy.load()
        self.conflicts = FieldRegionConflictDetector()

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
        competing = next((item for item in ranked[1:]
                          if _normalized(item.observed_text or "")
                          != _normalized(selected.observed_text or "")
                          and not (set(item.token_ids) & set(selected.token_ids))
                          and item.region_source.split("_TOKEN")[0].split("_LINE")[0]
                          == selected.region_source.split("_TOKEN")[0].split("_LINE")[0]
                          and (item.semantic_confidence or 0) >= .75), None)
        ambiguity_margin = (
            self.policy.ambiguity_margin
            if definition.datatype in {
                "DATE", "PERSON_NAME", "PERSON_OR_ORGANIZATION"
            }
            else .005
        )
        ownership, ownership_confidence, ownership_reasons = self.conflicts.classify(
            observation, definition, selected, competing,
            ambiguity_margin=ambiguity_margin,
        )
        reasons = [
            "BOUNDED_ALIAS_MATCH", "MULTI_CANDIDATE_REGION_RANKING",
            "ANCHOR_RELATIVE_GEOMETRY_VALIDATED", "OBSERVED_VALUE_SPAN_GEOMETRY",
            "NEIGHBOR_BOUNDARY_VALIDATED", f"CANDIDATE_SOURCE_{selected.region_source}",
        ]
        wrong_crop = ownership in WRONG_OWNERSHIP_OUTCOMES
        contract_region = selected.region_source == "ANCHOR_RELATIVE_CONTRACT"
        if not selected.observed_text and not contract_region:
            reasons.append("WRONG_CROP_EMPTY")
        if (selected.semantic_confidence or 0) < .20 and not contract_region:
            reasons.append("WRONG_CROP_SEMANTIC_MISMATCH")
        if selected.geometry_confidence < .50:
            reasons.append("WRONG_CROP_GEOMETRY")
        if "LABEL_ONLY" in selected.reason_codes:
            reasons.append("WRONG_CROP_LABEL_ONLY")
        if competing and selected.score - competing.score < ambiguity_margin:
            reasons.extend(("MULTIPLE_COMPETING_FIELD_VALUES", "WRONG_CROP_NEIGHBOR_FIELD"))
            wrong_crop = ownership in WRONG_OWNERSHIP_OUTCOMES
        if selected.score < self.policy.minimum_region_score and not contract_region:
            reasons.append("LOW_REGION_SCORE")

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
        reasons.extend(ownership_reasons)
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
            region_ownership=ownership.value,
            ownership_confidence=ownership_confidence,
            ownership_reason_codes=ownership_reasons,
            relationship_id=selected.relationship_id,
            relationship_type=selected.relationship_type,
            relationship_score=selected.relationship_score,
            relationship_geometry=selected.relationship_geometry,
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
        nearby: list[tuple[ObservationToken, float, str, str, str, dict[str, float]]] = []
        for token in observation.ocr_tokens:
            if token.token_id == anchor.token_id or self._is_label(token.text, aliases, definition):
                continue
            for index, relation in enumerate(definition.relationships):
                geometry, details = self._geometry(
                    token, anchor, observation, relation.relation
                )
                if geometry > 0:
                    relation_id = relation.relationship_id or (
                        f"{definition.form_family}.{definition.field_name}.relationship-{index + 1}"
                    )
                    source = f"ANCHOR_{relation.relation.upper()}"
                    nearby.append((
                        token, geometry, source, relation_id, relation.relation, details,
                    ))

        groups: list[tuple[list[ObservationToken], float, str, str, str, dict[str, float]]] = []
        textual = definition.datatype in {
            "PERSON_NAME", "PERSON_OR_ORGANIZATION", "ADDRESS", "TEXT"
        }
        if textual:
            by_line: dict[int, list[tuple[
                ObservationToken, float, str, str, str, dict[str, float]
            ]]] = {}
            for item in nearby:
                by_line.setdefault(item[0].line_index, []).append(item)
            for line in by_line.values():
                ordered = sorted(line, key=lambda item: item[0].bbox[0])
                runs: list[list[tuple[
                    ObservationToken, float, str, str, str, dict[str, float]
                ]]] = []
                for item in ordered:
                    if not runs:
                        runs.append([item])
                        continue
                    prior = runs[-1][-1][0]
                    gap = item[0].bbox[0] - prior.bbox[2]
                    height = max(1.0, prior.bbox[3] - prior.bbox[1])
                    if gap <= 3.5 * height:
                        runs[-1].append(item)
                    else:
                        runs.append([item])
                for run in runs:
                    limited = run[:6]
                    strongest = max(limited, key=lambda item: item[1])
                    direction = strongest[2]
                    groups.append(([item[0] for item in limited],
                                   sum(item[1] for item in limited) / len(limited),
                                   f"{direction}_LINE_SPAN", strongest[3], strongest[4],
                                   strongest[5]))
        groups.extend((
            [token], geometry, f"{source}_TOKEN_SPAN", relation_id, relation_type, details
        ) for token, geometry, source, relation_id, relation_type, details in nearby)

        candidates: list[LocalizationCandidate] = []
        seen: set[tuple[int, int, int, int]] = set()
        for tokens, geometry, source, relationship_id, relationship_type, details in groups:
            box = self._bounded_bbox(
                tokens, observation, definition, anchor, relationship_type
            )
            if box in seen or box[2] <= box[0] or box[3] <= box[1]:
                continue
            seen.add(box)
            observed = " ".join(token.text for token in tokens).strip()
            span = sum(token.confidence for token in tokens) / len(tokens)
            semantic = semantic_confidence(
                definition.datatype, observed, definition.field_name
            )
            cross_field = self._cross_field_confidence(
                box, observation, definition
            )
            score = self.policy.score(definition.form_family, definition.field_name,
                                      anchor=anchor_score, geometry=geometry, span=span,
                                      semantic=semantic, cross_field=cross_field)
            region_hash = _hash(observation.page_id, definition.field_name, source, box)
            candidates.append(LocalizationCandidate(
                candidate_id=region_hash[:24], bbox=box, region_source=source,
                token_ids=tuple(token.token_id for token in tokens), observed_text=observed,
                geometry_confidence=geometry, span_confidence=span,
                semantic_confidence=semantic, score=score,
                candidate_region_hash=region_hash,
                reason_codes=("TOKEN_DERIVED_REGION",),
                relationship_id=relationship_id,
                relationship_type=relationship_type,
                relationship_score=geometry,
                relationship_geometry=details,
            ))

        ax0, ay0, _, _ = anchor.bbox
        for index, relation in enumerate(definition.relationships):
            fallback = _clip((
                ax0 + relation.x0_offset * observation.width,
                ay0 + relation.y0_offset * observation.height,
                ax0 + relation.x1_offset * observation.width,
                ay0 + relation.y1_offset * observation.height,
            ), observation)
            if fallback[2] <= fallback[0] or fallback[3] <= fallback[1] or fallback in seen:
                continue
            relationship_id = relation.relationship_id or (
                f"{definition.form_family}.{definition.field_name}.relationship-{index + 1}"
            )
            contract_tokens = [
                token for token in observation.ocr_tokens
                if token.token_id != anchor.token_id
                and fallback[0] <= (token.bbox[0] + token.bbox[2]) / 2 <= fallback[2]
                and fallback[1] <= (token.bbox[1] + token.bbox[3]) / 2 <= fallback[3]
                and not self._is_label(token.text, aliases, definition)
            ]
            compatible = sorted(
                contract_tokens,
                key=lambda token: semantic_confidence(
                    definition.datatype, token.text, definition.field_name
                ),
                reverse=True,
            )
            contract_token = compatible[0] if compatible else None
            contract_text = contract_token.text if contract_token else None
            contract_semantic = semantic_confidence(
                definition.datatype, contract_text, definition.field_name
            )
            contract_span = contract_token.confidence if contract_token else 0.0
            candidate_box = (
                self._bounded_bbox(
                    [contract_token], observation, definition, anchor, relation.relation
                ) if contract_token and contract_semantic >= .50 else fallback
            )
            score = self.policy.score(
                definition.form_family, definition.field_name,
                anchor=anchor_score, geometry=.65, span=contract_span,
                semantic=contract_semantic,
            )
            region_hash = _hash(observation.page_id, definition.field_name,
                                "ANCHOR_RELATIVE_CONTRACT", candidate_box)
            candidates.append(LocalizationCandidate(
                candidate_id=region_hash[:24], bbox=candidate_box,
                region_source="ANCHOR_RELATIVE_CONTRACT", geometry_confidence=.65,
                token_ids=((contract_token.token_id,) if contract_token else ()),
                observed_text=contract_text,
                span_confidence=contract_span,
                semantic_confidence=contract_semantic,
                score=score,
                candidate_region_hash=region_hash,
                reason_codes=("FIELD_SPECIFIC_SPATIAL_CONTRACT",),
                relationship_id=relationship_id,
                relationship_type=relation.relation,
                relationship_score=.65,
                relationship_geometry={
                    "x0_offset": relation.x0_offset, "y0_offset": relation.y0_offset,
                    "x1_offset": relation.x1_offset, "y1_offset": relation.y1_offset,
                },
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
                  page: PageObservation, relation: str) -> tuple[float, dict[str, float]]:
        tcx = (token.bbox[0] + token.bbox[2]) / 2
        tcy = (token.bbox[1] + token.bbox[3]) / 2
        acx = (anchor.bbox[0] + anchor.bbox[2]) / 2
        acy = (anchor.bbox[1] + anchor.bbox[3]) / 2
        if relation == "right_of":
            dx = tcx - anchor.bbox[2]
            dy = abs(tcy - acy)
            if dx < -.015 * page.width or dx > .36 * page.width or dy > .055 * page.height:
                return 0.0, {"dx": dx, "dy": dy, "overlap": 0.0}
            overlap = _overlap_y(token, anchor)
            score = max(.05, min(1.0, .65 + .25 * overlap
                                 - .35 * max(0, dx) / (.36 * page.width)))
            score = max(.05, score - .012 * max(
                0, token.reading_order - anchor.reading_order - 1
            ))
            return score, {"dx": dx, "dy": dy, "overlap": overlap}
        dy = token.bbox[1] - anchor.bbox[3]
        dx = abs(tcx - acx)
        if dy < -.008 * page.height or dy > .10 * page.height or dx > .46 * page.width:
            return 0.0, {"dx": dx, "dy": dy, "overlap": 0.0}
        score = max(.05, min(1.0, .95 - .50 * max(0, dy) / (.10 * page.height)
                             - .20 * dx / (.46 * page.width)))
        score = max(.05, score - .012 * max(
            0, token.reading_order - anchor.reading_order - 1
        ))
        return score, {"dx": dx, "dy": dy, "overlap": _overlap_y(token, anchor)}

    @staticmethod
    def _bounded_bbox(tokens: list[ObservationToken], page: PageObservation,
                      definition: FieldDefinition, anchor: ObservationToken,
                      relationship_type: str) -> tuple[int, int, int, int]:
        height = max(token.bbox[3] - token.bbox[1] for token in tokens)
        textual = definition.datatype in {
            "PERSON_NAME", "PERSON_OR_ORGANIZATION", "ADDRESS", "TEXT"
        }
        left = .60 * height
        width = max(token.bbox[2] for token in tokens) - min(
            token.bbox[0] for token in tokens
        )
        if textual:
            right = max(5.5 * height, .90 * width)
        elif definition.field_name == "member_id":
            right = max(3.75 * height, .85 * width)
        elif definition.datatype == "NPI":
            right = max(3.75 * height, .55 * width)
        elif definition.datatype == "DATE":
            right = 2.25 * height
        elif definition.datatype == "TYPE_OF_BILL":
            right = 1.50 * height
        elif definition.datatype == "CURRENCY":
            right = 1.75 * height
        else:
            right = 2.25 * height
        top_padding = .20 * height
        bottom_padding = .80 * height
        x0 = min(token.bbox[0] for token in tokens) - left
        y0 = min(token.bbox[1] for token in tokens) - top_padding
        x1 = max(token.bbox[2] for token in tokens) + right
        y1 = max(token.bbox[3] for token in tokens) + bottom_padding
        if relationship_type == "right_of":
            x0 = max(x0, anchor.bbox[2] + .10 * height)
        declared_labels = {
            _normalized(item) for item in (
                *definition.negative_labels,
                *(name.replace("_", " ") for name in definition.neighbor_fields),
            )
        }
        for other in page.ocr_tokens:
            if other in tokens or not any(
                label and (label in _normalized(other.text) or _normalized(other.text) in label)
                for label in declared_labels
            ):
                continue
            if other.bbox[0] >= max(token.bbox[2] for token in tokens) and (
                other.bbox[1] < y1 and other.bbox[3] > y0
            ):
                x1 = min(x1, other.bbox[0] - .20 * height)
        return _clip((x0, y0, x1, y1), page)

    @staticmethod
    def _cross_field_confidence(
        box: tuple[int, int, int, int], observation: PageObservation,
        definition: FieldDefinition,
    ) -> float | None:
        declared = {
            _normalized(item) for item in (
                *definition.negative_labels,
                *(name.replace("_", " ") for name in definition.neighbor_fields),
            )
        }
        if not declared:
            return None
        contaminated = any(
            _overlap_bbox_token(box, token)
            and any(label and (label in _normalized(token.text) or _normalized(token.text) in label)
                    for label in declared)
            for token in observation.ocr_tokens
        )
        return 0.0 if contaminated else 1.0


def _overlap_bbox_token(box: tuple[int, int, int, int], token: ObservationToken) -> bool:
    return min(box[2], token.bbox[2]) > max(box[0], token.bbox[0]) and min(
        box[3], token.bbox[3]
    ) > max(box[1], token.bbox[1])
