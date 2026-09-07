"""Frozen review-only UB box-10 date assembly from existing OCR."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class BirthdateTopology:
    form_type: str = "UB"
    field_name: str = "patient_dob"
    normalized_region: tuple[float, float, float, float] = (0.012, 0.108, 0.129, 0.130)
    version: str = "ub-box10-v1"


def discover(
    tokens: Sequence[TextLine],
    *,
    form_type: str,
    field_name: str,
    width: int,
    height: int,
    topology: BirthdateTopology,
) -> list[dict]:
    if (
        form_type != "UB"
        or form_type != topology.form_type
        or field_name != "patient_dob"
        or field_name != topology.field_name
        or width <= 0
        or height <= 0
        or topology.version != "ub-box10-v1"
    ):
        return []
    l, t, r, b = topology.normalized_region
    if not (0 <= l < r <= 1 and 0 <= t < b <= 1):
        return []
    result = []
    for index, token in enumerate(tokens):
        if not (
            l <= token.x0 / width < token.x1 / width <= r
            and t <= token.y0 / height < token.y1 / height <= b
        ):
            continue
        match = re.fullmatch(r"([0-9]{8})_?", token.text.strip())
        if not match:
            continue
        raw = match[1]
        try:
            value = date(int(raw[4:]), int(raw[:2]), int(raw[2:4])).isoformat()
        except ValueError:
            continue
        result.append(
            {
                "field_name": field_name,
                "value": value,
                "token_indices": [index],
                "normalized_bbox": [
                    token.x0 / width,
                    token.y0 / height,
                    token.x1 / width,
                    token.y1 / height,
                ],
                "review_only": True,
                "reason": "UB_BOX10_OBSERVED_MMDDYYYY; OPTIONAL_TRAILING_RULE_ARTIFACT",
            }
        )
    # Competing valid dates in one cell are unresolved, not ranked using truth.
    if len({r["value"] for r in result}) > 1:
        return []
    return result[:1]
