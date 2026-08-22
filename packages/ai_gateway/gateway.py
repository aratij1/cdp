"""Policy enforcement, budgets, rate limits, retries and circuit breaking."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, date, datetime
from time import monotonic

from packages.ai_gateway.contracts import (
    AIProvider,
    FieldResolutionRequest,
    FieldResolutionResponse,
    GatewayAuditRecord,
    TenantAIPolicy,
)
from packages.observability.metrics import (
    ai_gateway_cost_usd_total,
    ai_gateway_requests_total,
    ai_gateway_tokens_total,
)


class GatewayPolicyError(PermissionError):
    pass


class GatewayBudgetError(RuntimeError):
    pass


class GatewayRateLimitError(RuntimeError):
    pass


class GatewayCircuitOpenError(RuntimeError):
    pass


class AIGateway:
    def __init__(
        self,
        policies: dict[str, TenantAIPolicy],
        *,
        audit_sink: Callable[[GatewayAuditRecord], None] | None = None,
        failure_threshold: int = 3,
        circuit_reset_seconds: float = 30,
    ) -> None:
        self._policies = policies
        self._audit_sink = audit_sink or (lambda _record: None)
        self._spent: dict[tuple[str, date], float] = defaultdict(float)
        self._reserved: dict[tuple[str, date], float] = defaultdict(float)
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._failures: dict[tuple[str, str], int] = defaultdict(int)
        self._opened_at: dict[tuple[str, str], float] = {}
        self._failure_threshold = failure_threshold
        self._reset_seconds = circuit_reset_seconds

    def _authorize(
        self, request: FieldResolutionRequest, provider: AIProvider, estimated_cost_usd: float
    ) -> TenantAIPolicy:
        policy = self._policies.get(request.tenant_id)
        if policy is None or not policy.enabled:
            raise GatewayPolicyError("external AI is disabled for tenant")
        if request.contains_phi and not policy.phi_external_processing_approved:
            raise GatewayPolicyError("tenant PHI external-processing approval is missing")
        if provider.region not in policy.approved_regions:
            raise GatewayPolicyError("provider region is not approved for tenant")
        if provider.model_name not in policy.allowed_models:
            raise GatewayPolicyError("model is not allowlisted for tenant")
        if len(request.crop_bytes) > policy.max_crop_bytes:
            raise GatewayPolicyError("crop exceeds tenant request-size limit")
        budget_key = (request.tenant_id, datetime.now(UTC).date())
        if self._spent[budget_key] + self._reserved[budget_key] + estimated_cost_usd > policy.daily_budget_usd:
            raise GatewayBudgetError("tenant daily AI budget would be exceeded")
        now = monotonic()
        window = self._requests[request.tenant_id]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= policy.max_requests_per_minute:
            raise GatewayRateLimitError("tenant AI request rate exceeded")
        circuit_key = (provider.provider_name, provider.model_name)
        opened = self._opened_at.get(circuit_key)
        if opened is not None and now - opened < self._reset_seconds:
            raise GatewayCircuitOpenError("provider circuit is open")
        if opened is not None:
            self._opened_at.pop(circuit_key, None)
            self._failures[circuit_key] = 0
        window.append(now)
        self._reserved[budget_key] += estimated_cost_usd
        return policy

    async def resolve(
        self,
        request: FieldResolutionRequest,
        provider: AIProvider,
        *,
        estimated_cost_usd: float,
        trace_id: str | None = None,
    ) -> FieldResolutionResponse:
        policy = self._authorize(request, provider, estimated_cost_usd)
        circuit_key = (provider.provider_name, provider.model_name)
        started = monotonic()
        response = None
        error: Exception | None = None
        for attempt in range(policy.max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    provider.resolve(request), timeout=policy.timeout_seconds
                )
                error = None
                break
            except Exception as exc:  # provider/schema failures are audited and fail closed
                error = exc
                transient = isinstance(exc, (TimeoutError, ConnectionError))
                if transient and attempt < policy.max_retries:
                    await asyncio.sleep(0)
                    continue
                break
        latency = (monotonic() - started) * 1000
        if error is not None or response is None:
            budget_key = (request.tenant_id, datetime.now(UTC).date())
            self._reserved[budget_key] = max(
                0.0, self._reserved[budget_key] - estimated_cost_usd
            )
            self._failures[circuit_key] += 1
            if self._failures[circuit_key] >= self._failure_threshold:
                self._opened_at[circuit_key] = monotonic()
            self._audit_sink(
                GatewayAuditRecord(
                    request_id=request.request_id,
                    tenant_id=request.tenant_id,
                    document_id=request.document_id,
                    field_name=request.field_name,
                    crop_sha256=request.crop_sha256,
                    provider=provider.provider_name,
                    model=provider.model_name,
                    region=provider.region,
                    outcome="FAILED",
                    latency_ms=latency,
                    estimated_cost_usd=estimated_cost_usd,
                    actual_cost_usd=0,
                    input_tokens=0,
                    output_tokens=0,
                    trace_id=trace_id,
                )
            )
            ai_gateway_requests_total.labels(
                provider=provider.provider_name, model=provider.model_name, outcome="FAILED"
            ).inc()
            raise error
        self._failures[circuit_key] = 0
        budget_key = (request.tenant_id, datetime.now(UTC).date())
        self._reserved[budget_key] = max(
            0.0, self._reserved[budget_key] - estimated_cost_usd
        )
        self._spent[budget_key] += response.actual_cost_usd
        self._audit_sink(
            GatewayAuditRecord(
                request_id=request.request_id,
                tenant_id=request.tenant_id,
                document_id=request.document_id,
                field_name=request.field_name,
                crop_sha256=request.crop_sha256,
                provider=provider.provider_name,
                model=provider.model_name,
                region=provider.region,
                outcome="SUCCEEDED",
                latency_ms=latency,
                estimated_cost_usd=estimated_cost_usd,
                actual_cost_usd=response.actual_cost_usd,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                trace_id=trace_id,
            )
        )
        ai_gateway_requests_total.labels(
            provider=provider.provider_name, model=provider.model_name, outcome="SUCCEEDED"
        ).inc()
        ai_gateway_cost_usd_total.labels(
            tenant_id=request.tenant_id,
            provider=provider.provider_name,
            model=provider.model_name,
        ).inc(response.actual_cost_usd)
        ai_gateway_tokens_total.labels(
            provider=provider.provider_name, model=provider.model_name, direction="input"
        ).inc(response.input_tokens)
        ai_gateway_tokens_total.labels(
            provider=provider.provider_name, model=provider.model_name, direction="output"
        ).inc(response.output_tokens)
        return response
