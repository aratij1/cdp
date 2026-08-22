"""Four-level field criticality policy with legacy compatibility."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml

DEFAULT_CRITICALITY_PATH = Path(__file__).resolve().parent.parent / "config" / "field_criticality.yaml"


class CriticalityLevel(StrEnum):
    C0 = "C0"
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"


class CriticalityPolicy:
    def __init__(self, levels: dict[str, CriticalityLevel], version: str) -> None:
        self.levels = levels
        self.version = version

    def for_field(self, field_name: str) -> CriticalityLevel:
        return self.levels.get(field_name, CriticalityLevel.C1)

    @classmethod
    def load(cls, path: str | Path) -> CriticalityPolicy:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            {name: CriticalityLevel(level) for name, level in payload["fields"].items()},
            str(payload["version"]),
        )
