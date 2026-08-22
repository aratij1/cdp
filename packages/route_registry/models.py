from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import ConfigDict, Field, model_validator

from packages.domain.common import DomainModel


class RouteLifecycle(StrEnum):
    DISABLED = "DISABLED"
    EXPERIMENTAL = "EXPERIMENTAL"
    EVALUATION_ONLY = "EVALUATION_ONLY"
    SHADOW = "SHADOW"
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    DEPRECATED = "DEPRECATED"


class RouteDefinition(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    route_id: str
    field: str
    form: str
    primary_engine: str
    confirmation_engine: str
    preprocessing_profile: str
    policy_version: str
    benchmark_dataset: str
    sample_count: int = Field(ge=0)
    standalone_accuracy: float | None = Field(default=None, ge=0, le=1)
    agreement_precision: float | None = Field(default=None, ge=0, le=1)
    false_agreement_count: int = Field(ge=0)
    mean_latency_ms: float | None = Field(default=None, ge=0)
    cost_per_call_usd: float | None = Field(default=None, ge=0)
    cost_status: str
    status: RouteLifecycle
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_scope: str | None = None

    @model_validator(mode="after")
    def production_approval_has_provenance(self):
        if self.status is RouteLifecycle.PRODUCTION_APPROVED and (
            not self.approved_by or self.approved_at is None
        ):
            raise ValueError("production-approved route requires approved_by and approved_at")
        return self

    def applies_to(self, document_family: str) -> bool:
        return self.form == "*" or self.form.upper() == document_family.upper()

    def compatibility_spec(self) -> dict:
        """Read-only compatibility view for existing evidence-routing callers."""
        return {
            **self.model_dump(mode="json"),
            "document_family": self.form,
            "primary": self.primary_engine,
            "confirmation": self.confirmation_engine,
            "state": self.status.value,
        }
