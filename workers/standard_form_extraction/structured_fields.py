"""Deterministic reconstruction/parsing helpers for common claim fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import product

from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class PersonName:
    source: str
    last: str
    first: str
    middle: str = ""
    suffix: str = ""


_SUFFIXES = {"JR", "SR", "II", "III", "IV", "MD", "DO"}


def parse_person_name(source: str, semantics: str = "AUTO") -> PersonName:
    clean = re.sub(r"\s+", " ", source.strip())
    if not clean:
        return PersonName(source, "", "")
    comma_form = "," in clean
    tokens = clean.replace(",", " ").split()
    suffix = tokens.pop() if tokens and tokens[-1].rstrip(".").upper() in _SUFFIXES else ""
    mode = semantics.upper()
    if mode == "AUTO":
        mode = "LAST_FIRST_MIDDLE" if comma_form else "FIRST_MIDDLE_LAST"
    if mode in {"LAST_FIRST_MIDDLE", "LAST_FIRST"}:
        last, first, middle = tokens[0], tokens[1] if len(tokens) > 1 else "", " ".join(tokens[2:])
    else:
        first, last = tokens[0], tokens[-1] if len(tokens) > 1 else ""
        middle = " ".join(tokens[1:-1])
    return PersonName(clean, last, first, middle, suffix)


def reconstruct_reading_order(lines: list[TextLine], line_tolerance: float = 0.6) -> str:
    """Cluster by baseline, then order tokens left-to-right within each line."""
    clusters: list[list[TextLine]] = []
    for token in sorted(lines, key=lambda item: (item.y0, item.x0)):
        height = max(token.y1 - token.y0, 1)
        center = (token.y0 + token.y1) / 2
        target = next(
            (
                cluster
                for cluster in clusters
                if abs(center - sum((item.y0 + item.y1) / 2 for item in cluster) / len(cluster))
                <= line_tolerance * height
            ),
            None,
        )
        if target is None:
            clusters.append([token])
        else:
            target.append(token)
    return "\n".join(
        " ".join(item.text for item in sorted(cluster, key=lambda item: item.x0))
        for cluster in clusters
    )


_CONFUSIONS = {
    "O": "0",
    "0": "O",
    "I": "1",
    "L": "1",
    "1": "I",
    "S": "5",
    "5": "S",
    "B": "8",
    "8": "B",
    "Z": "2",
    "2": "Z",
    "G": "6",
    "6": "G",
}


def constrained_alternatives(
    value: str,
    validator,
    maximum_substitutions: int = 2,
) -> list[str]:
    """Return only confusion alternatives that pass the complete validator."""
    positions = [index for index, char in enumerate(value) if char.upper() in _CONFUSIONS]
    accepted: list[str] = []
    for count in range(1, min(maximum_substitutions, len(positions)) + 1):
        for selected in product((False, True), repeat=len(positions)):
            if sum(selected) != count:
                continue
            chars = list(value)
            for use, position in zip(selected, positions, strict=True):
                if use:
                    original = chars[position]
                    replacement = _CONFUSIONS[original.upper()]
                    chars[position] = replacement.lower() if original.islower() else replacement
            candidate = "".join(chars)
            if validator(candidate) and candidate not in accepted:
                accepted.append(candidate)
    return accepted
