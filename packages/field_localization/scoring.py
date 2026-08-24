"""Versioned, field-aware scoring for localization candidates.

Scores rank regions only. They never replace deterministic field validation or
authorize machine acceptance.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from pydantic import Field

from packages.domain.common import DomainModel


class LocalizationWeights(DomainModel):
    anchor: float = Field(ge=0)
    geometry: float = Field(ge=0)
    span: float = Field(ge=0)
    semantic: float = Field(ge=0)
    template: float = Field(ge=0)
    cross_field: float = Field(ge=0)


class LocalizationScoringPolicy(DomainModel):
    version: str
    minimum_region_score: float = Field(ge=0, le=1)
    ambiguity_margin: float = Field(ge=0, le=1)
    default: LocalizationWeights
    fields: dict[str, LocalizationWeights] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> LocalizationScoringPolicy:
        source = path or Path(__file__).resolve().parents[2] / "config/localization_scoring_v1.yaml"
        return cls.model_validate(yaml.safe_load(Path(source).read_text("utf-8")))

    def weights_for(self, family: str, field_name: str) -> LocalizationWeights:
        return self.fields.get(f"{family}.{field_name}", self.fields.get(field_name, self.default))

    def score(
        self,
        family: str,
        field_name: str,
        *,
        anchor: float,
        geometry: float,
        span: float,
        semantic: float,
        template: float = 0.0,
        cross_field: float = 0.0,
    ) -> float:
        weights = self.weights_for(family, field_name)
        values = {
            "anchor": anchor,
            "geometry": geometry,
            "span": span,
            "semantic": semantic,
            "template": template,
            "cross_field": cross_field,
        }
        total = sum(getattr(weights, name) for name in values)
        if total <= 0:
            return 0.0
        return min(1.0, sum(getattr(weights, name) * value for name, value in values.items()) / total)


def semantic_confidence(datatype: str, value: str | None, field_name: str | None = None) -> float:
    """Return a ranking feature, never an acceptance decision."""
    raw = (value or "").strip()
    if not raw:
        return 0.0
    compact = re.sub(r"\s+", " ", raw)
    digits = re.sub(r"\D", "", raw)
    if field_name == "relationship":
        return 1.0 if raw.upper() in {"SELF", "SPOUSE", "CHILD", "OTHER"} else 0.0
    if field_name == "member_id":
        valid = bool(re.fullmatch(r"[A-Za-z0-9-]{5,24}", raw))
        mixed = bool(re.search(r"[A-Za-z]", raw) and re.search(r"\d", raw))
        return 1.0 if valid and mixed else .45 if valid else .1
    if datatype == "NPI":
        return 1.0 if _valid_npi(digits) else 0.35 if len(digits) == 10 else 0.0
    if datatype == "DATE":
        parsed = _date(raw)
        today = datetime.now(UTC).date()
        latest = date(today.year + 5, 12, 31) if field_name == "service_date" else today
        return 1.0 if parsed and date(1900, 1, 1) <= parsed <= latest else 0.0
    if datatype == "ICD_CODE":
        values = compact.split()
        valid = r"[A-TV-Z][0-9A-Z][0-9A-Z](?:\.?[0-9A-Z]{1,4})?"
        return 1.0 if values and all(re.fullmatch(valid, item, re.IGNORECASE) for item in values) else 0.1
    if datatype == "CPT_HCPCS":
        return 1.0 if re.fullmatch(r"(?:\d{5}|[A-Z]\d{4})", compact, re.IGNORECASE) else 0.1
    if datatype == "CURRENCY":
        return 1.0 if re.fullmatch(r"\$?\d[\d,]*(?:\.\d{1,2})?", raw) else 0.1
    if datatype == "TYPE_OF_BILL":
        return 1.0 if re.fullmatch(r"0?\d{3}", digits) else 0.1
    if datatype == "TAX_IDENTIFIER":
        return 1.0 if len(digits) == 9 else 0.2
    if datatype == "ALPHANUMERIC_ID":
        return 0.95 if re.fullmatch(r"[A-Za-z0-9-]{5,24}", raw) else 0.15
    if datatype in {"PERSON_NAME", "PERSON_OR_ORGANIZATION", "ADDRESS", "TEXT"}:
        if any(label in raw.upper() for label in (
            "SYNTHETIC", "DOCUMENT", "OFFICIAL FORM", "PATIENT NAME",
            "PROVIDER NAME", "RELATIONSHIP", "TOTAL CHARGE",
        )):
            return 0.05
        words = re.findall(r"[A-Za-z][A-Za-z.'-]*", raw)
        if not words or re.fullmatch(r"[\d\W_]+", raw):
            return 0.0
        return min(1.0, 0.55 + 0.15 * len(words))
    return 0.7


def _date(value: str) -> date | None:
    digits = re.sub(r"\D", "", value)
    candidates = [value]
    if len(digits) == 8:
        candidates.extend((
            f"{digits[:4]}-{digits[4:6]}-{digits[6:]}",
            f"{digits[4:]}-{digits[:2]}-{digits[2:4]}",
        ))
    for candidate in candidates:
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _valid_npi(value: str) -> bool:
    if not re.fullmatch(r"\d{10}", value):
        return False
    digits = [int(item) for item in "80840" + value]
    total = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
