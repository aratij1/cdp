"""Configurable evidence requirements by document family, field, and criticality."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from packages.criticality import CriticalityLevel

DEFAULT_EVIDENCE_POLICY_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "field_evidence_policies.yaml"
)


class EvidenceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criticality: CriticalityLevel | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)
    any_of: list[list[str]] = Field(default_factory=list)

    def evaluate(self, signals: set[str]) -> tuple[bool, list[str]]:
        if not self.any_of:
            return True, []
        missing = ["+".join(requirement) for requirement in self.any_of if not set(requirement) <= signals]
        return len(missing) < len(self.any_of), missing


class EvidencePolicyRegistry:
    def __init__(
        self,
        defaults: dict[CriticalityLevel, EvidenceRule],
        fields: dict[tuple[str, str], EvidenceRule],
        version: str,
    ) -> None:
        self.defaults = defaults
        self.fields = fields
        self.version = version

    def rule_for(
        self, document_family: str, field_name: str, criticality: CriticalityLevel
    ) -> EvidenceRule:
        return (
            self.fields.get((document_family.upper(), field_name))
            or self.fields.get(("*", field_name))
            or self.defaults[criticality]
        )

    @classmethod
    def load(cls, path: str | Path = DEFAULT_EVIDENCE_POLICY_PATH) -> EvidencePolicyRegistry:
        payload = yaml.safe_load(Path(path).read_text("utf-8"))
        defaults = {
            CriticalityLevel(level): EvidenceRule.model_validate(rule)
            for level, rule in payload["defaults"].items()
        }
        fields = {
            (str(rule["document_family"]).upper(), str(rule["field_name"])): EvidenceRule.model_validate(
                {key: value for key, value in rule.items() if key not in {"document_family", "field_name"}}
            )
            for rule in payload["fields"]
        }
        return cls(defaults, fields, str(payload["version"]))
