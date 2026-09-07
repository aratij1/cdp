"""Experimental normalized name topology; contains no image identity or truth."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from workers.field_candidates.label_token_recovery import Token
from workers.field_candidates.source_reviewed_anchor import (
    AUTHORITY,
    SourceReviewedAnchor,
    name_candidates,
)
from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True, slots=True)
class NameFieldTopology:
    form_type: str
    field_name: str
    normalized_region: tuple[float, float, float, float]
    token_alignment_rules: str = "BELOW_OWN_LABEL_ABOVE_OWN_ADDRESS"
    max_token_gap: float = 0.18
    row_tolerance: float = 0.6
    provenance_version: str = "dev-source-only-v1"


@dataclass(frozen=True)
class Registration:
    dx: float = 0
    dy: float = 0
    skew: float = 0

    def valid(self) -> bool:
        return abs(self.dx) <= 0.02 and abs(self.dy) <= 0.02 and abs(self.skew) <= 0.02

    def point(self, x: float, y: float) -> tuple[float, float]:
        return x + self.dx + self.skew * (y - 0.5), y + self.dy


def is_name_label(text: str) -> bool:
    compact = re.sub(r"[^a-z]", "", text.lower())
    return any(part in compact for part in ("name", "namo", "namf", "nane", "namel"))


def discover(
    tokens: Sequence[TextLine],
    *,
    form_type: str,
    field_name: str,
    width: int,
    height: int,
    topology: NameFieldTopology,
    registration: Registration = Registration(),
) -> tuple[list[dict], list[dict]]:
    if (
        form_type not in {"CMS1500", "UB"}
        or form_type != topology.form_type
        or field_name != topology.field_name
        or field_name not in {"patient_name", "insured_name"}
        or width <= 0
        or height <= 0
        or not registration.valid()
        or topology.provenance_version != "dev-source-only-v1"
    ):
        return [], []
    l, t, r, b = topology.normalized_region
    if not (
        0 <= l < r <= 1
        and 0 <= t < b <= 1
        and 0 < topology.max_token_gap <= 0.2
        and 0 < topology.row_tolerance <= 0.6
    ):
        return [], []
    normalized = []
    for token in tokens:
        corners = [
            registration.point(x / width, y / height)
            for x in (token.x0, token.x1)
            for y in (token.y0, token.y1)
        ]
        normalized.append(
            TextLine(
                token.text,
                min(x for x, y in corners),
                min(y for x, y in corners),
                max(x for x, y in corners),
                max(y for x, y in corners),
                token.confidence,
            )
        )
    labels = [x for x in normalized if l <= x.x0 < r and t <= x.y0 < b and is_name_label(x.text)]
    if not labels:
        return [], []
    label = min(labels, key=lambda x: x.y0)
    top = label.y1 - 0.0015
    boundaries = [
        x.y0
        for x in normalized
        if l <= x.x0 < r
        and top < x.y0 < b
        and ("address" in x.text.lower() or x.text.lstrip().startswith(("5.", "7.")))
    ]
    bottom = min(boundaries) + 0.0055 if boundaries else b
    items = [
        (i, x)
        for i, x in enumerate(normalized)
        if l <= x.x0 < x.x1 <= r and top <= x.y0 < x.y1 <= bottom
    ]
    observations = []
    if any(
        re.fullmatch(r"SAME(?: AS ABOVE)?|SELF", x.text.strip(), re.IGNORECASE) for _, x in items
    ):
        observations.append(
            {
                "field_name": field_name,
                "reason": "SOURCE_PLACEHOLDER",
                "resolution": "NO_GOVERNED_FIELD_INHERITANCE_AUTHORITY",
            }
        )
        return [], observations
    # Assemble bounded rows; a large gap starts a new row rather than joining cells.
    rows: list[list[tuple[int, TextLine]]] = []
    for item in sorted(items, key=lambda pair: (pair[1].y0, pair[1].x0)):
        if not re.fullmatch(r"[A-Za-z ,.'-]+", item[1].text.strip()) or is_name_label(item[1].text):
            continue
        center = (item[1].y0 + item[1].y1) / 2
        for row in rows:
            first = row[0][1]
            last = max(row, key=lambda pair: pair[1].x1)[1]
            if (
                abs(center - (first.y0 + first.y1) / 2)
                < min(first.y1 - first.y0, item[1].y1 - item[1].y0) * topology.row_tolerance
                and item[1].x0 - last.x1 <= topology.max_token_gap
            ):
                row.append(item)
                break
        else:
            rows.append([item])
    output = []
    anchor = SourceReviewedAnchor(
        "", form_type, field_name, (l, t, r, b), (l, top, r, bottom), "form-topology-v1", AUTHORITY
    )
    for row in rows:
        typed_row: list[tuple[int, Token]] = [(i, token) for i, token in row]
        for candidate in name_candidates(typed_row, anchor):
            output.append(
                {
                    "field_name": field_name,
                    "value": candidate.value,
                    "token_indices": list(candidate.token_indices),
                    "normalized_bbox": candidate.bbox,
                    "review_only": True,
                    "reason": "FROZEN_DEV_NORMALIZED_NAME_TOPOLOGY",
                }
            )
    return output, observations
