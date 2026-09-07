"""Source-attested, review-only total-cell localization and digit assembly.

No reference values, claim aliases, field lengths or digit corrections are inputs.
The caller must validate the sealed source review before supplying a topology.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class ChargeCell:
    form_type: str
    source_sha256: str
    normalized_region: tuple[float, float, float, float]
    cents_separator: float
    source_reviewed: bool = False
    cents_column_verified: bool = False
    role: str = "CLAIM_TOTAL"
    version: str = "charge-cell-v1"


def valid_cell(cell: ChargeCell, form_type: str, source_sha256: str) -> bool:
    l, t, r, b = cell.normalized_region
    return (
        form_type in {"CMS1500", "UB"}
        and cell.form_type == form_type
        and cell.source_sha256 == source_sha256
        and bool(re.fullmatch(r"[0-9a-f]{64}", source_sha256))
        and cell.source_reviewed
        and cell.role == "CLAIM_TOTAL"
        and cell.version == "charge-cell-v1"
        and 0 <= l < cell.cents_separator < r <= 1
        and 0 <= t < b <= 1
    )


def ocr_allowed(
    cell: ChargeCell,
    *,
    form_type: str,
    source_sha256: str,
    value_visible: bool,
    primary_value_present: bool,
) -> bool:
    return (
        valid_cell(cell, form_type, source_sha256) and value_visible and not primary_value_present
    )


def numeric_text(raw: str) -> str | None:
    # S/s may only be a detached or boundary currency glyph, never an internal digit.
    m = re.fullmatch(r"[ $Ss]*([0-9]+(?:,[0-9]{3})*(?:[.: ][0-9]{2})?)[ $Ss]*", raw.strip())
    return m[1].replace(",", "") if m else None


def discover(
    tokens: Sequence[TextLine],
    *,
    form_type: str,
    source_sha256: str,
    width: int,
    height: int,
    cell: ChargeCell,
    pilot: str,
) -> list[dict]:
    if (
        width <= 0
        or height <= 0
        or pilot not in {"A", "B"}
        or not valid_cell(cell, form_type, source_sha256)
    ):
        return []
    l, top, right, bottom = cell.normalized_region
    selected = []
    for i, token in enumerate(tokens):
        # Permit only a trailing currency glyph to overlap the next box; digits
        # must start inside and the token centre must belong to the total cell.
        contained = token.x1 / width <= right + 0.002
        boundary_currency = bool(re.fullmatch(r"[ $Ss]*[0-9,. :]+[ $Ss]+", token.text))
        if not (
            l <= token.x0 / width < (token.x0 + token.x1) / (2 * width) < right
            and top <= (token.y0 + token.y1) / (2 * height) <= bottom
            and (contained or (boundary_currency and token.x1 / width <= right + 0.025))
        ):
            continue
        raw = numeric_text(token.text)
        if raw is not None:
            selected.append((i, token, raw))
    result = []

    def emit(value: str, parts: list, reason: str) -> None:
        result.append(
            {
                "field_name": "total_charge",
                "value": format(Decimal(value), ".2f"),
                "token_indices": [p[0] for p in parts],
                "raw_tokens": [
                    {
                        "text": p[1].text,
                        "bbox": [p[1].x0, p[1].y0, p[1].x1, p[1].y1],
                        "confidence": p[1].confidence,
                    }
                    for p in parts
                ],
                "region": list(cell.normalized_region),
                "source_sha256": source_sha256,
                "reason": reason,
                "review_only": True,
                "authority": "ENGINEERING_ONLY",
            }
        )

    for part in selected:
        _, token, raw = part
        if pilot == "A" and re.fullmatch(r"[0-9]+\.[0-9]{2}", raw):
            emit(raw, [part], "EXPLICIT_DECIMAL_IN_CLAIM_TOTAL_CELL")
        elif pilot == "B" and cell.cents_column_verified:
            if re.fullmatch(r"[0-9]+[: ][0-9]{2}", raw):
                emit(
                    raw.replace(":", ".").replace(" ", "."),
                    [part],
                    "OBSERVED_DOLLARS_CENTS_SEPARATOR",
                )
            elif (
                re.fullmatch(r"[0-9]{3,}", raw)
                and token.x0 / width < cell.cents_separator < token.x1 / width
            ):
                emit(raw[:-2] + "." + raw[-2:], [part], "DIGITS_SPAN_SOURCE_VERIFIED_CENTS_COLUMN")
    if pilot == "B" and cell.cents_column_verified:
        dollars = [
            p
            for p in selected
            if p[2].isdigit()
            and p[1].x0 / width < cell.cents_separator
            and (p[1].x0 + p[1].x1) / (2 * width) < cell.cents_separator
        ]
        cents = [
            p
            for p in selected
            if re.fullmatch(r"[0-9]{2}", p[2])
            and (p[1].x0 + p[1].x1) / (2 * width) > cell.cents_separator
        ]
        if len(dollars) == len(cents) == 1:
            a, b = dollars[0], cents[0]
            if a[0] != b[0] and a[1].x0 < b[1].x0 and max(a[1].y0, b[1].y0) < min(a[1].y1, b[1].y1):
                emit(a[2] + "." + b[2], [a, b], "SEPARATE_OBSERVED_DOLLARS_AND_TWO_CENTS_DIGITS")
    # Distinct readings remain alternatives. Never resolve conflicts using truth.
    return list({r["value"]: r for r in result}.values())
