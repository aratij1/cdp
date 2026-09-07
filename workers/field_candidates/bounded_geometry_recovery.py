"""Field-specific geometry proposals from observed OCR; no canonical authority."""

from __future__ import annotations

import re
from collections.abc import Sequence

from workers.field_candidates.label_token_recovery import Token, TokenCandidate, label_text, labels
from workers.field_candidates.name_interpretations import interpret_complete_name

# Bounds are fractions of the image, applied only around an observed label.
BOUNDS = {
    "patient_name": (0.36, 0.055),
    "insured_name": (0.36, 0.055),
    "member_id": (0.28, 0.04),
    "patient_dob": (0.12, 0.025),
    "total_charge": (0.22, 0.035),
    "principal_diagnosis": (0.15, 0.03),
}


def source_amount_components(text: str) -> str | None:
    """Assemble observed dollar/cents groups only inside a proven total region."""
    value = text.strip()
    if re.fullmatch(r"\$?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?", value):
        return value
    parts = re.fullmatch(r"\$?([0-9]+)[ :]+([0-9]{2})", value)
    if parts:
        return f"{parts[1]}.{parts[2]}"
    span = re.fullmatch(r"(\$?[0-9]+\.[0-9]{2})\s+[$s]", value)
    return span[1] if span else None


def source_last_first_label(text: str) -> bool:
    """Preserve explicit source instruction order; no fuzzy convention inference."""
    return bool(re.search(r"last\s*name.*first\s*name", label_text(text)))


def generate_geometry(tokens: Sequence[Token], *, width: int, height: int) -> list[TokenCandidate]:
    if width <= 0 or height <= 0:
        raise ValueError("POSITIVE_IMAGE_DIMENSIONS_REQUIRED")
    anchors = labels(tokens)
    # An exact stand-alone total label permits receipt-style same-row association.
    anchors += [
        (i, "total_charge")
        for i, t in enumerate(tokens)
        if re.fullmatch(r"total(?: amount| charges?| fees?)?", label_text(t.text))
        and (i, "total_charge") not in anchors
    ]
    result = []
    for i, field in anchors:
        anchor = tokens[i]
        lh = max(1.0, anchor.y1 - anchor.y0)
        wx, hy = BOUNDS[field]
        table_header = field == "total_charge" and any(
            abs(t.y0 - anchor.y0) <= lh
            and re.search(r"hcpcs|non.?cover|serv.*units|rev[ .]*c(?:d|o)", t.text, re.IGNORECASE)
            for t in tokens
        )
        if table_header:
            continue
        next_column = min(
            [float(width), anchor.x0 + width * wx]
            + [
                t.x0
                for j, t in enumerate(tokens)
                if j != i
                and t.x0 > anchor.x0 + lh
                and abs(t.y0 - anchor.y0) < lh
                and (
                    any(j == k for k, _ in anchors)
                    or re.match(r"^\s*\d{1,2}[a-z]?[. ]?[A-Z]", t.text)
                )
            ]
        )
        selected = []
        for j, t in enumerate(tokens):
            if j == i or any(j == k for k, _ in anchors):
                continue
            below = (
                anchor.y1 - lh * 0.15 <= t.y0 <= anchor.y1 + height * hy
                and anchor.x0 - lh * 0.3 <= t.x0
                and t.x1 <= next_column + lh * 0.3
            )
            beside = (
                field == "total_charge"
                and abs(t.y0 - anchor.y0) <= lh * 0.6
                and anchor.x1 <= t.x0
                and t.x1 <= anchor.x1 + width * 0.28
            )
            if not (below or beside) or not t.text.strip():
                continue
            if re.match(r"^\s*\d{1,2}[a-z]?\.\s*[A-Za-z]", t.text):
                continue
            text = t.text.strip()
            if field in {"patient_name", "insured_name"} and (
                any(ch.isdigit() for ch in text)
                or len(text.split()) < 2
                or re.search(
                    r"\b(?:address|street|city|state|signature|date|relationship|same|self)\b",
                    text,
                    re.IGNORECASE,
                )
            ):
                continue
            if field == "total_charge":
                amount = source_amount_components(text)
                if amount is None:
                    continue
                text = amount
            if field == "member_id" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{1,39}", text):
                continue
            selected.append((abs(t.y0 - anchor.y1), abs(t.x0 - anchor.x0), j, text))
        for _, _, j, text in sorted(selected)[:3]:
            t = tokens[j]
            values = [
                (
                    text,
                    "SOURCE_NUMERIC_COMPONENT_ASSEMBLY"
                    if field == "total_charge" and text != t.text.strip()
                    else "FIELD_BOUNDED_SINGLE_TOKEN",
                )
            ]
            if field in {"patient_name", "insured_name"} and (
                text.count(",") == 1 or source_last_first_label(anchor.text)
            ):
                values += [
                    (
                        " ".join(v for v in (n.first, n.middle, n.last, n.suffix) if v),
                        "SOURCE_NAME_CONVENTION",
                    )
                    for n in interpret_complete_name(text, "LAST_FIRST")
                    if n.convention == "LAST_FIRST"
                ]
            for value, reason in values:
                result.append(
                    TokenCandidate(
                        field,
                        value,
                        (t.x0, t.y0, t.x1, t.y1),
                        (j,),
                        i,
                        (anchor.x0, anchor.y0, anchor.x1, anchor.y1),
                        reason,
                    )
                )
    return result


def generate_birthdate(tokens: Sequence[Token], *, width: int, height: int) -> list[TokenCandidate]:
    """UB field-10 birth date, proven by its neighboring sex label; review only.

    This compound topology never authorizes UB identity. Eight observed digits
    are segmented as the existing US date convention; no character repair or
    century inference is allowed.
    """
    from datetime import date
    from difflib import SequenceMatcher

    result = []
    for i, anchor in enumerate(tokens):
        text = re.sub(r"[^a-z0-9]", "", anchor.text.lower())
        if not text.startswith("10") or SequenceMatcher(None, text[2:], "birthdate").ratio() < 0.65:
            continue
        lh = max(1.0, anchor.y1 - anchor.y0)
        neighbors = [
            t
            for t in tokens
            if anchor.x1 < t.x0 <= anchor.x0 + width * 0.16
            and abs(t.y0 - anchor.y0) <= lh
            and re.fullmatch(r"(?:11)?se?x(?:12)?", re.sub(r"[^a-z0-9]", "", t.text.lower()))
        ]
        if len(neighbors) != 1:
            continue
        for j, t in enumerate(tokens):
            if not (
                anchor.x0 <= t.x0 < t.x1 <= neighbors[0].x0 + lh * 0.15
                and anchor.y1 <= t.y0 < t.y1 <= anchor.y1 + min(height * 0.03, lh * 2.0)
            ):
                continue
            match = re.fullmatch(r"([0-9]{8})_?", t.text.strip())
            if not match:
                continue
            digits = match[1]
            try:
                value = date(int(digits[4:]), int(digits[:2]), int(digits[2:4])).isoformat()
            except ValueError:
                continue
            result.append(
                TokenCandidate(
                    "patient_dob",
                    value,
                    (t.x0, t.y0, t.x1, t.y1),
                    (j,),
                    i,
                    (anchor.x0, anchor.y0, anchor.x1, anchor.y1),
                    "BOX_10_BIRTHDATE_SEX_COMPOUND_ANCHOR",
                )
            )
    return result


def generate_structural(
    tokens: Sequence[Token], *, width: int, height: int
) -> list[TokenCandidate]:
    """Replace generic date rows only when a compound birth-date region is proven."""
    from workers.field_candidates.label_token_recovery import generate

    base = generate(tokens, width=width, height=height)
    geometry = generate_geometry(tokens, width=width, height=height)
    dates = generate_birthdate(tokens, width=width, height=height)
    if dates:
        # Sex and adjacent admission cells are not birth-date alternatives.
        # Keep the source OCR untouched; emit typed date assembly from its own cell.
        base = [c for c in base if c.field_name != "patient_dob"]
        geometry = [c for c in geometry if c.field_name != "patient_dob"]
    return base + geometry + dates
