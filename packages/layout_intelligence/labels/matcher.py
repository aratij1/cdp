from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

import yaml

from packages.domain.common import BoundingBox
from packages.layout_intelligence.models import LabelMatch, LayoutLine
from packages.layout_intelligence.reading_order import normalize_text


class LabelMatcher:
    def __init__(self, config: dict, minimum_similarity: float = .84) -> None:
        self.fields = config["fields"]
        self.minimum_similarity = minimum_similarity

    @classmethod
    def from_yaml(cls, path: str | Path) -> "LabelMatcher":
        return cls(yaml.safe_load(Path(path).read_text("utf-8")))

    def detect(self, lines: list[LayoutLine]) -> list[LabelMatch]:
        matches = []
        for index, line in enumerate(lines):
            normalized_line = normalize_text(line.text)
            for field, spec in self.fields.items():
                for alias in spec["aliases"]:
                    normalized_alias = normalize_text(alias)
                    score = _similarity(normalized_alias, normalized_line)
                    if score >= self.minimum_similarity:
                        matches.append(LabelMatch(
                            field_name=field, alias=alias, text=line.text,
                            bbox=line.bbox, similarity=score, line_index=index,
                        ))
                        break
        return matches

    def datatype(self, field_name: str) -> str:
        return self.fields[field_name]["datatype"]

    def vocabulary(self) -> set[str]:
        return {normalize_text(alias) for spec in self.fields.values() for alias in spec["aliases"]}


def _contiguous_token_match(alias_tokens: list[str], text_tokens: list[str]) -> bool:
    """True if alias_tokens appears as one uninterrupted, in-order run inside
    text_tokens. Scattered tokens that merely co-occur somewhere in a longer,
    unrelated line (e.g. "policy" ... "number" either side of "group or
    feca") must not count as the alias phrase being present."""
    n = len(alias_tokens)
    if n == 0:
        return False
    return any(
        text_tokens[start:start + n] == alias_tokens
        for start in range(len(text_tokens) - n + 1)
    )


def _similarity(alias: str, text: str) -> float:
    if alias == text:
        return 1.0
    alias_tokens, text_tokens = alias.split(), text.split()
    if _contiguous_token_match(alias_tokens, text_tokens):
        # The alias phrase appears intact and in order -- this covers the
        # common "Label: rest of line is the value" pattern regardless of
        # how long the value is. What it must NOT credit is what the old
        # implementation did: crediting alias tokens that merely co-occur
        # somewhere in an unrelated line without appearing together as a
        # phrase (handled by requiring contiguity above), or a bare
        # substring match with no word-boundary awareness at all.
        return 1.0
    # No fallback token-set-overlap score here on purpose: scoring by
    # "each alias token appears somewhere in the text" (regardless of
    # order or adjacency) is exactly the unsafe behavior being removed --
    # e.g. "policy" and "number" both appearing, far apart, in "11.
    # INSURED'S POLICY GROUP OR FECA NUMBER" must not score as a match
    # for the "policy number" alias. Only reward genuine near-identical
    # wording (OCR noise tolerance), not incidental word co-occurrence.
    return SequenceMatcher(None, alias, text).ratio()


def label_firewall(value: str, vocabulary: set[str]) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    return not any(normalized == label or normalized in label for label in vocabulary)
