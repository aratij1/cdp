"""Review-only normalized member-ID discovery; no reference input or acceptance."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class MemberIdTopology:
    form_type: str = "CMS1500"
    field_name: str = "member_id"
    normalized_region: tuple[float, float, float, float] = (0.59, 0.112, 0.90, 0.151)
    row_tolerance: float = 0.5
    maximum_candidates: int = 2
    version: str = "non-name-dev-v1"


def discover_member_ids(
    tokens: Sequence[TextLine],
    *,
    form_type: str,
    field_name: str,
    width: int,
    height: int,
    topology: MemberIdTopology,
) -> list[dict]:
    if (
        form_type != "CMS1500"
        or form_type != topology.form_type
        or field_name != "member_id"
        or field_name != topology.field_name
        or width <= 0
        or height <= 0
        or topology.version != "non-name-dev-v1"
        or not 1 <= topology.maximum_candidates <= 2
    ):
        return []
    l, t, r, b = topology.normalized_region
    if not (0 <= l < r <= 1 and 0 <= t < b <= 1 and 0 < topology.row_tolerance <= 0.5):
        return []
    selected = [
        (i, x)
        for i, x in enumerate(tokens)
        if l <= x.x0 / width < x.x1 / width <= r and t <= x.y0 / height < x.y1 / height <= b
    ]
    # The observed box-4 name label is a hard lower boundary when available.
    labels = [
        x.y0
        for _, x in selected
        if any(s in re.sub(r"[^a-z]", "", x.text.lower()) for s in ("name", "namf", "namo", "nane"))
    ]
    if labels:
        selected = [(i, x) for i, x in selected if x.y1 <= min(labels) + height * 0.002]
    eligible = [(i, x) for i, x in selected if re.fullmatch(r"[A-Za-z0-9/-]+", x.text.strip())]
    rows: list[list[tuple[int, TextLine]]] = []
    for item in sorted(eligible, key=lambda pair: (pair[1].y0, pair[1].x0)):
        center = (item[1].y0 + item[1].y1) / 2
        for row in rows:
            first = row[0][1]
            if (
                abs(center - (first.y0 + first.y1) / 2)
                <= min(first.y1 - first.y0, item[1].y1 - item[1].y0) * topology.row_tolerance
            ):
                row.append(item)
                break
        else:
            rows.append([item])
    output = []
    for row in rows:
        row.sort(key=lambda pair: pair[1].x0)
        # Join only visibly contiguous fragments. Preserve all observed symbols.
        groups: list[list[tuple[int, TextLine]]] = []
        for item in row:
            if groups:
                prev = groups[-1][-1][1]
                char_width = min(
                    (prev.x1 - prev.x0) / max(1, len(prev.text)),
                    (item[1].x1 - item[1].x0) / max(1, len(item[1].text)),
                )
                if item[1].x0 - prev.x1 <= char_width * 0.5:
                    groups[-1].append(item)
                    continue
            groups.append([item])
        for group in groups:
            value = "".join(x.text.strip() for _, x in group)
            if not (
                len(value) >= 2
                and any(c.isdigit() for c in value)
                and re.fullmatch(r"[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*", value)
            ):
                continue
            bbox = (
                min(x.x0 for _, x in group),
                min(x.y0 for _, x in group),
                max(x.x1 for _, x in group),
                max(x.y1 for _, x in group),
            )
            output.append(
                {
                    "field_name": "member_id",
                    "value": value,
                    "token_indices": [i for i, _ in group],
                    "normalized_bbox": [
                        bbox[0] / width,
                        bbox[1] / height,
                        bbox[2] / width,
                        bbox[3] / height,
                    ],
                    "reason": "CMS_1A_NORMALIZED_ID_CELL",
                    "review_only": True,
                }
            )
    return output[: topology.maximum_candidates]
