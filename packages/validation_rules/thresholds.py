"""Per-field confidence thresholds, keyed by criticality -- loaded from
`config/validation/*.yaml`. Deliberately not a single document-level
confidence gate: a CRITICAL field (e.g. provider NPI) needs a much higher
OCR confidence to auto-pass than a NON_CRITICAL one (e.g. a free-text
remarks field) before deterministic validation is even attempted."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field

from packages.domain.common import DomainModel
from packages.domain.enums import FieldCriticality

DEFAULT_VALIDATION_CONFIG_DIR = (
    Path(__file__).resolve().parent.parent.parent / "config" / "validation"
)

DEFAULT_CRITICAL_THRESHOLD = 0.90
DEFAULT_NON_CRITICAL_THRESHOLD = 0.70


class FieldThreshold(DomainModel):
    field_name: str
    criticality: FieldCriticality
    min_confidence: float = Field(ge=0, le=1)
    rule: str | None = None


class ThresholdRegistry:
    def __init__(self, thresholds: list[FieldThreshold] | None = None) -> None:
        self._by_field: dict[str, FieldThreshold] = {t.field_name: t for t in thresholds or []}

    def get(self, field_name: str) -> FieldThreshold | None:
        return self._by_field.get(field_name)

    def min_confidence_for(
        self, field_name: str, criticality: FieldCriticality | None = None
    ) -> float:
        threshold = self._by_field.get(field_name)
        if threshold is not None:
            return threshold.min_confidence
        if criticality is FieldCriticality.CRITICAL:
            return DEFAULT_CRITICAL_THRESHOLD
        return DEFAULT_NON_CRITICAL_THRESHOLD

    def meets_threshold(
        self, field_name: str, confidence: float, criticality: FieldCriticality | None = None
    ) -> bool:
        return confidence >= self.min_confidence_for(field_name, criticality)

    @classmethod
    def load_from_directory(
        cls, directory: Path = DEFAULT_VALIDATION_CONFIG_DIR
    ) -> ThresholdRegistry:
        thresholds: list[FieldThreshold] = []
        for path in sorted(directory.glob("*.yaml")):
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            thresholds.extend(FieldThreshold.model_validate(item) for item in data)
        return cls(thresholds)
