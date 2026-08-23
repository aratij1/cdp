"""Versioned field criticality and claim-blocking policy."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ConfigDict, Field

from packages.criticality import CriticalityLevel
from packages.domain.common import DomainModel

DEFAULT_FIELD_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "field_acceptance_policies.yaml"
)


class FieldPolicy(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str
    canonical_field_name: str
    aliases: tuple[str, ...] = ()
    configured: bool = True
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
        family = {
            **self._forms.get("*", {}),
            **self._forms.get(document_family.upper(), {}),
        }
        canonical_name = field_name
        field_spec = family.get(field_name)
        if field_spec is None:
            matched = next(
                (
                    (name, value)
                    for name, value in family.items()
                    if field_name in set(value.get("aliases", []))
                ),
                None,
            )
            if matched:
                canonical_name, field_spec = matched
        explicitly_configured = field_spec is not None
        configured = explicitly_configured or self.version == "field-acceptance-v1"
        spec = {**self._default, **(field_spec or {})}
        return FieldPolicy(
            policy_id=f"{document_family.upper()}:{canonical_name}",
            canonical_field_name=canonical_name,
            configured=configured,
            **spec,
        )

    def canonical_name(self, document_family: str, field_name: str) -> str:
        return self.for_field(document_family, field_name).canonical_field_name

    def is_explicitly_configured(self, document_family: str, field_name: str) -> bool:
        family = {
            **self._forms.get("*", {}),
            **self._forms.get(document_family.upper(), {}),
        }
        return field_name in family or any(
            field_name in set(value.get("aliases", [])) for value in family.values()
        )

    def configured_fields(self, document_family: str) -> list[str]:
        """Return explicitly governed fields; the fail-closed default is not a form requirement."""
        return sorted(self._forms.get(document_family.upper(), {}))

    def required_fields(self, document_family: str) -> list[str]:
        return [
            name
            for name in self.configured_fields(document_family)
            if self.for_field(document_family, name).required
        ]
