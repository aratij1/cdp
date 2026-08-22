"""Versioned field criticality and claim-blocking policy."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ConfigDict, Field

from packages.criticality import CriticalityLevel
from packages.domain.common import DomainModel

DEFAULT_FIELD_POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "field_acceptance_policies.yaml"


class FieldPolicy(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str
    criticality: CriticalityLevel
    required: bool
    blocks_stp: bool
    requires_review_when_unresolved: bool
    business_impact: str
    financial_impact: str = "none"
    identity_impact: str = "none"
    clinical_impact: str = "none"
    compliance_impact: str = "none"
    downstream_consumers: list[str] = Field(default_factory=list)
    reason: str


class FieldPolicyRegistry:
    def __init__(self, payload: dict) -> None:
        self.version = str(payload["version"])
        self._default = payload["default"]
        self._forms = payload.get("forms", {})

    @classmethod
    def load(cls, path: str | Path = DEFAULT_FIELD_POLICY_PATH) -> FieldPolicyRegistry:
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def for_field(self, document_family: str, field_name: str) -> FieldPolicy:
        family = self._forms.get(document_family.upper(), {})
        spec = {**self._default, **family.get(field_name, {})}
        return FieldPolicy(
            policy_id=f"{document_family.upper()}:{field_name}",
            **spec,
        )

    def configured_fields(self, document_family: str) -> list[str]:
        """Return explicitly governed fields; the fail-closed default is not a form requirement."""
        return sorted(self._forms.get(document_family.upper(), {}))

    def required_fields(self, document_family: str) -> list[str]:
        return [
            name for name in self.configured_fields(document_family)
            if self.for_field(document_family, name).required
        ]
