"""Selective cloud resolution that emits auxiliary evidence, never accepted truth."""

from __future__ import annotations

import re
from collections import Counter

from pydantic import Field

from packages.ai_gateway.contracts import (
    AIProvider,
    FieldResolutionRequest,
    FieldResolutionResponse,
)
from packages.ai_gateway.gateway import AIGateway
from packages.domain.common import DomainModel
from packages.policy_engine import PolicyAction


class SelectiveResolutionError(RuntimeError):
    """Raised when a request violates selective-resolution invariants."""


class AuxiliaryCandidate(DomainModel):
    value: str | None
    confidence: float = Field(ge=0, le=1)
    source: str
    model: str
    model_version: str
    validation_results: tuple[str, ...] = ()
    insufficient_evidence: bool
    actual_cost_usd: float = Field(default=0, ge=0)
    acceptance_authority: bool = False


class SelectiveResolutionResult(DomainModel):
    candidate: AuxiliaryCandidate
    requires_reconciliation: bool = True
    action: PolicyAction


_SUPPORTED = {
    PolicyAction.GEMINI_CHEAP,
    PolicyAction.GEMINI_STANDARD,
    PolicyAction.GEMINI_ADVANCED,
    PolicyAction.TEXTRACT,
}
_GEMINI = {
    PolicyAction.GEMINI_CHEAP,
    PolicyAction.GEMINI_STANDARD,
    PolicyAction.GEMINI_ADVANCED,
}
_MODEL_FOR_ACTION = {
    PolicyAction.GEMINI_CHEAP: "gemini-2.5-flash-lite",
    PolicyAction.GEMINI_STANDARD: "gemini-2.5-flash",
    PolicyAction.GEMINI_ADVANCED: "gemini-2.5-pro",
    PolicyAction.TEXTRACT: "DetectDocumentText",
}


class SelectiveResolutionCoordinator:
    def __init__(
        self,
        gateway: AIGateway,
        providers: dict[str, AIProvider],
        *,
        max_cloud_attempts_per_field: int = 2,
    ) -> None:
        self._gateway = gateway
        self._providers = providers
        self._max_attempts = max_cloud_attempts_per_field
        self._attempts: Counter[tuple[str, str]] = Counter()

    async def resolve(
        self,
        action: PolicyAction,
        request: FieldResolutionRequest,
        *,
        estimated_cost_usd: float,
        trace_id: str | None = None,
    ) -> SelectiveResolutionResult:
        if action not in _SUPPORTED:
            raise SelectiveResolutionError(f"{action.value} is not a cloud-resolution action")
        if request.scope not in {"FIELD_CROP", "TABLE_CROP"}:
            raise SelectiveResolutionError("cloud resolution accepts crop-only requests")
        if action in _GEMINI and "npi" in request.field_name.lower():
            raise SelectiveResolutionError("Gemini is not an approved resolver for NPI fields")
        key = (request.document_id, request.field_name)
        if self._attempts[key] >= self._max_attempts:
            raise SelectiveResolutionError("per-field cloud attempt limit exhausted")
        model = _MODEL_FOR_ACTION[action]
        provider = self._providers.get(model)
        if provider is None:
            raise SelectiveResolutionError(f"provider is not configured for {action.value}")

        self._attempts[key] += 1
        response = await self._gateway.resolve(
            request,
            provider,
            estimated_cost_usd=estimated_cost_usd,
            trace_id=trace_id,
        )
        candidate = self._candidate(request, response)
        return SelectiveResolutionResult(candidate=candidate, action=action)

    @staticmethod
    def _candidate(
        request: FieldResolutionRequest, response: FieldResolutionResponse
    ) -> AuxiliaryCandidate:
        checks: list[str] = []
        value = response.value.strip() if response.value else None
        insufficient = response.insufficient_evidence or not value
        if value and request.allowed_pattern:
            if re.fullmatch(request.allowed_pattern, value):
                checks.append("allowed_pattern_passed")
            else:
                checks.append("allowed_pattern_failed")
                insufficient = True
        return AuxiliaryCandidate(
            value=value,
            confidence=response.confidence,
            source=response.provider,
            model=response.model,
            model_version=response.model_version,
            validation_results=tuple(checks),
            insufficient_evidence=insufficient,
            actual_cost_usd=response.actual_cost_usd,
            acceptance_authority=False,
        )
