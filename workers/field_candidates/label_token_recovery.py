"""Review-only label-local candidates from existing OCR geometry.

No form identity, truth, fixed coordinates, acceptance policy or reference value
is an input. These candidates cannot authorize canonical extraction or outputs.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol

from workers.field_candidates.name_interpretations import interpret_complete_name


class Token(Protocol):
    @property
    def text(self) -> str: ...
    @property
    def x0(self) -> float: ...
    @property
    def y0(self) -> float: ...
    @property
    def x1(self) -> float: ...
    @property
    def y1(self) -> float: ...
    @property
    def confidence(self) -> float: ...


@dataclass(frozen=True)
class TokenCandidate:
    field_name: str
    value: str
    bbox: tuple[float, float, float, float]
    token_indices: tuple[int, ...]
    label_index: int
    label_bbox: tuple[float, float, float, float]
    reason: str
    review_only: bool = True


LABELS = {
    "patient_name": (r"patient(?: ?s)? name", r"name of patient"),
    "insured_name": (r"insured(?: ?s)? name", r"subscriber name"),
    "member_id": (r"insured(?: ?s)? i ?d number", r"member id", r"member number", r"subscriber id"),
    "patient_dob": (r"patient(?: ?s)? birth ?date", r"patient(?: ?s)? date of birth"),
    "total_charge": (r"total charges?",),
    "principal_diagnosis": (r"principal diag(?:nosis)?", r"prin diag(?:nosis)?"),
}


def label_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


ALIASES = {
    "patient_name": ("patient name", "patients name", "name of patient"),
    "insured_name": ("insured name", "insureds name", "subscriber name"),
    "member_id": (
        "insureds id number",
        "insured id number",
        "member id",
        "member number",
        "subscriber id",
    ),
    "patient_dob": ("patients birthdate", "patient birthdate", "date of birth", "birthdate"),
    "total_charge": ("total charge", "total charges"),
    "principal_diagnosis": ("principal diagnosis", "principal diag", "prin diag", "princ diag"),
}


def labels(tokens: Sequence[Token]) -> list[tuple[int, str]]:
    found = []
    for i, token in enumerate(tokens):
        # Confusable-character handling applies to label detection only. Original
        # OCR values and geometry remain untouched. Require a label-prefix match.
        text = re.sub(r"^\s*\d{1,2}(?:[a-z](?=[. ]))?[. ]*", "", token.text.casefold())
        text = label_text(text)
        if text.startswith(("other ", "employer ")):
            continue
        words = text.split()
        matches = []
        for field, aliases in ALIASES.items():
            score = 0.0
            for alias in aliases:
                expected = alias.replace(" ", "")
                for count in range(1, min(5, len(words)) + 1):
                    prefix = "".join(words[:count]).translate(str.maketrans("105", "ios"))
                    if len(prefix) >= 7:
                        score = max(score, SequenceMatcher(None, expected, prefix).ratio())
            if score >= 0.88:
                matches.append((score, field))
        matches.sort(reverse=True)
        if matches and (len(matches) == 1 or matches[0][0] - matches[1][0] >= 0.08):
            found.append((i, matches[0][1]))
    return found


def generate(tokens: Sequence[Token], *, width: int, height: int) -> list[TokenCandidate]:
    """Use token-level labels instead of merging independent form columns.

    Search only the first two text rows below a proven label, capped at 5% page
    height and the next neighboring label. Preserve alternative evidence rather
    than modifying runtime ranking or accepting any candidate.
    """
    if width <= 0 or height <= 0:
        raise ValueError("POSITIVE_IMAGE_DIMENSIONS_REQUIRED")
    found = labels(tokens)
    result = []
    for index, field in found:
        anchor = tokens[index]
        label_h = max(1.0, anchor.y1 - anchor.y0)
        if field == "total_charge" and any(
            abs(t.y0 - anchor.y0) <= label_h
            and re.search(r"hcpcs|non.?cover|serv.*units|rev[ .]*c(?:d|o)", t.text, re.IGNORECASE)
            for t in tokens
        ):
            # A charge-column label does not make its first line a claim total.
            # Require an observed totals row aligned to that charge column.
            totals = [
                (j, t)
                for j, t in enumerate(tokens)
                if t.y0 > anchor.y1 and re.fullmatch(r"totals?", label_text(t.text))
            ]
            next_columns = [
                t.x0 for t in tokens if abs(t.y0 - anchor.y0) <= label_h and t.x0 > anchor.x1
            ]
            edge = min([float(width), anchor.x1 + width * 0.12, *next_columns])
            for total_i, total in totals:
                for j, t in enumerate(tokens):
                    if (
                        abs(t.y0 - total.y0) <= label_h
                        and anchor.x0 <= t.x0 < t.x1 <= edge + label_h * 0.3
                        and re.fullmatch(r"\$?[0-9]+(?:\.[0-9]{1,2})?", t.text.strip())
                    ):
                        result.append(
                            TokenCandidate(
                                field,
                                t.text.strip(),
                                (t.x0, t.y0, t.x1, t.y1),
                                (j,),
                                total_i,
                                (total.x0, total.y0, total.x1, total.y1),
                                "TOTALS_ROW_CHARGE_COLUMN_INTERSECTION",
                            )
                        )
            continue

        # All OCR label-like cells serve as column boundaries, not just fields
        # targeted in this experiment. A field number is layout evidence only.
        adjacent = [
            t.x0
            for j, t in enumerate(tokens)
            if j != index
            and t.x0 > anchor.x0 + label_h
            and abs(t.y0 - anchor.y0) <= label_h
            and (re.match(r"^\s*\d{1,2}[a-z]?[. ]?[A-Z]", t.text) or any(j == n for n, _ in found))
        ]
        right = min(
            [
                float(width),
                anchor.x0 + min(width * 0.45, max(anchor.x1 - anchor.x0, width * 0.20)),
                *adjacent,
            ]
        )
        bottom = min(float(height), anchor.y1 + min(height * 0.05, label_h * 3.5))
        local = [
            (j, t)
            for j, t in enumerate(tokens)
            if j != index
            and t.y0 >= anchor.y1 - label_h * 0.15
            and t.y0 < bottom
            and t.x0 >= anchor.x0 - label_h * 0.4
            and t.x1 <= right + label_h * 0.4
            and not any(j == n for n, _ in found)
            and not re.match(r"^\s*\d{1,2}[a-z]?\.\s*[A-Za-z]", t.text)
        ]
        local.sort(key=lambda pair: (pair[1].y0, pair[1].x0))
        rows: list[list[tuple[int, Token]]] = []
        for pair in local:
            target = next((r for r in rows if abs(r[0][1].y0 - pair[1].y0) <= label_h * 0.6), None)
            if target is None:
                rows.append([pair])
            else:
                target.append(pair)
        for row in rows[:2]:
            row.sort(key=lambda pair: pair[1].x0)
            value = " ".join(t.text.strip() for _, t in row).strip()
            if not value:
                continue
            variants = [(value, "LABEL_LOCAL_ROW")]
            if field == "total_charge":
                variants = [
                    (t.text.strip(), "LABEL_LOCAL_NUMERIC_TOKEN")
                    for _, t in row
                    if re.fullmatch(
                        r"\$?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?", t.text.strip()
                    )
                ] + variants
            if field in {"patient_name", "insured_name"}:
                anchor_text = label_text(anchor.text)
                source_names = [
                    t.text.strip()
                    for _, t in row
                    if len(t.text.split()) >= 2 and not any(ch.isdigit() for ch in t.text)
                ]
                variants = [(v, "LABEL_LOCAL_NAME_TOKEN") for v in source_names] + variants
                if ("last" in anchor_text and "first" in anchor_text) or any(
                    v.count(",") == 1 for v, _ in variants
                ):
                    assembled = []
                    for v, _ in variants:
                        if (
                            not ("last" in anchor_text and "first" in anchor_text)
                            and v.count(",") != 1
                        ):
                            continue
                        for item in interpret_complete_name(v, "LAST_FIRST"):
                            if item.convention == "LAST_FIRST":
                                assembled.append(
                                    (
                                        " ".join(
                                            x
                                            for x in [
                                                item.first,
                                                item.middle,
                                                item.last,
                                                item.suffix,
                                            ]
                                            if x
                                        ),
                                        "LABEL_PROVEN_LAST_FIRST_ASSEMBLY"
                                        if "last" in anchor_text and "first" in anchor_text
                                        else "COMMA_NAME_INTERPRETATION_REVIEW_ONLY",
                                    )
                                )
                    variants = assembled + variants
            for value, reason in variants:
                result.append(
                    TokenCandidate(
                        field,
                        value,
                        (
                            min(t.x0 for _, t in row),
                            min(t.y0 for _, t in row),
                            max(t.x1 for _, t in row),
                            max(t.y1 for _, t in row),
                        ),
                        tuple(j for j, _ in row),
                        index,
                        (anchor.x0, anchor.y0, anchor.x1, anchor.y1),
                        reason,
                    )
                )
    return result
