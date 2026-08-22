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


def _similarity(alias: str, text: str) -> float:
    if alias == text or alias in text:
        return 1.0
    alias_tokens, text_tokens = set(alias.split()), set(text.split())
    token_score = len(alias_tokens & text_tokens) / max(len(alias_tokens), 1)
    edit_score = SequenceMatcher(None, alias, text).ratio()
    return max(token_score, edit_score)


def label_firewall(value: str, vocabulary: set[str]) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    return not any(normalized == label or normalized in label for label in vocabulary)
