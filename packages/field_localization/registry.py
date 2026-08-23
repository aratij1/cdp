from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .contracts import FieldDefinition


class FieldDefinitionRegistry:
    def __init__(self, definitions: tuple[FieldDefinition, ...], version: str):
        self.definitions = definitions
        self.version = version

    @classmethod
    @lru_cache(maxsize=8)
    def load(cls, path: str | Path) -> FieldDefinitionRegistry:
        payload = yaml.safe_load(Path(path).read_text("utf-8"))
        version = payload["version"]
        definitions = tuple(FieldDefinition.model_validate({
            **item, "definition_version": version,
        }) for item in payload["fields"])
        return cls(definitions, version)

    def for_family(self, family: str) -> tuple[FieldDefinition, ...]:
        return tuple(item for item in self.definitions if item.form_family == family)

    def get(self, family: str, field_name: str) -> FieldDefinition:
        return next(item for item in self.definitions
                    if item.form_family == family and item.field_name == field_name)
