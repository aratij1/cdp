"""Conservative token fusion for noncritical structured descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass

CONTROLLED_TERMS = {"ANCILLARY"}


@dataclass(frozen=True)
class TextCandidate:
    value: str
    confidence: float
    independence_group: str


def fuse_noncritical_description(candidates: list[TextCandidate]) -> str | None:
    """Fuse equal-length lines from independent OCR architectures.

    Controlled terminology may repair a one-character disagreement. Other token
    disagreements retain the token from the highest-confidence complete line.
    This function must never be used for identity, address or clinical fields.
    """
    usable = [candidate for candidate in candidates if candidate.value.strip()]
    if len({candidate.independence_group for candidate in usable}) < 2:
        return None
    pairs: list[tuple[int, float, TextCandidate, TextCandidate]] = []
    for index, left in enumerate(usable):
        left_tokens = _tokens(left.value)
        for right in usable[index + 1:]:
            if left.independence_group == right.independence_group:
                continue
            right_tokens = _tokens(right.value)
            if not left_tokens or len(left_tokens) != len(right_tokens):
                continue
            distance = sum(
                _edit_distance(_normalized(lhs), _normalized(rhs))
                for lhs, rhs in zip(left_tokens, right_tokens, strict=True)
            )
            pairs.append((distance, -(left.confidence + right.confidence), left, right))
    if not pairs:
        return None
    _, _, first, second = min(pairs, key=lambda item: (item[0], item[1]))
    ranked = sorted((first, second), key=lambda item: item.confidence, reverse=True)
    token_lines = [_tokens(item.value) for item in ranked]
    if not token_lines[0] or len({len(tokens) for tokens in token_lines}) != 1:
        return None
    output: list[str] = []
    for index in range(len(token_lines[0])):
        choices = [tokens[index] for tokens in token_lines]
        normalized = [_normalized(token) for token in choices]
        if len(set(normalized)) == 1:
            output.append(choices[0])
            continue
        controlled = next((token for token in choices if _normalized(token) in CONTROLLED_TERMS), None)
        if controlled and all(
            _edit_distance(_normalized(controlled), token) <= 1 for token in normalized
        ):
            output.append(controlled)
            continue
        if all(_edit_distance(normalized[0], token) <= 2 for token in normalized[1:]):
            output.append(choices[0])
            continue
        return None
    return " ".join(output)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", value)


def _normalized(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row, lhs in enumerate(left, 1):
        current = [row]
        for column, rhs in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (lhs != rhs),
            ))
        previous = current
    return previous[-1]
