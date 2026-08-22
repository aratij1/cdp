from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from packages.domain.common import DomainModel, utcnow


class FieldResolutionRequest(DomainModel):
    request_id: str
    tenant_id: str
    document_id: str
    field_name: str
    expected_type: str
    crop_bytes: bytes = Field(repr=False)
    crop_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    scope: Literal["FIELD_CROP", "TABLE_CROP"] = "FIELD_CROP"
    allowed_pattern: str | None = None
    nearby_label: str | None = None
    ocr_candidates: list[str] = Field(default_factory=list, max_length=10)
    validation_errors: list[str] = Field(default_factory=list, max_length=20)
    contains_phi: bool = True
    remaining_sla_ms: int | None = Field(default=None, ge=0)

    @field_validator("crop_bytes")
    @classmethod
    def crop_must_be_bounded(cls, value: bytes) -> bytes:
        if not value:
            raise ValueError("field crop must not be empty")
        return value

    @model_validator(mode="after")
    def crop_hash_must_match(self):
        if sha256(self.crop_bytes).hexdigest().lower() != self.crop_sha256.lower():
            raise ValueError("crop_sha256 does not match crop bytes")
        return self


class FieldResolutionResponse(DomainModel):
    value: str | None
    confidence: float = Field(ge=0, le=1)
    insufficient_evidence: bool
    provider: str
    model: str
    model_version: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    actual_cost_usd: float = Field(default=0, ge=0)


class TenantAIPolicy(DomainModel):
    tenant_id: str
    enabled: bool = False
    phi_external_processing_approved: bool = False
    approved_regions: set[str] = Field(default_factory=set)
    allowed_models: set[str] = Field(default_factory=set)
    daily_budget_usd: float = Field(default=0, ge=0)
    max_requests_per_minute: int = Field(default=0, ge=0)
    max_crop_bytes: int = Field(default=2_000_000, gt=0)
    timeout_seconds: float = Field(default=15, gt=0)
    max_retries: int = Field(default=1, ge=0, le=3)


class GatewayAuditRecord(DomainModel):
    request_id: str
    tenant_id: str
    document_id: str
    field_name: str
    crop_sha256: str
    provider: str
    model: str
    region: str
    outcome: str
    latency_ms: float = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
    actual_cost_usd: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AIProvider(Protocol):
    provider_name: str
    model_name: str
    model_version: str
    region: str

    async def resolve(self, request: FieldResolutionRequest) -> FieldResolutionResponse: ...
