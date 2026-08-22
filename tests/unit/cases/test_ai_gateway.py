import hashlib

import pytest

from packages.ai_gateway.contracts import (
    FieldResolutionRequest,
    FieldResolutionResponse,
    TenantAIPolicy,
)
from packages.ai_gateway.gateway import (
    AIGateway,
    GatewayBudgetError,
    GatewayCircuitOpenError,
    GatewayPolicyError,
    GatewayRateLimitError,
)


class Provider:
    provider_name = "vertex_ai_gemini"
    model_name = "gemini-2.5-flash-lite"
    model_version = "2.5"
    region = "us-central1"

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    async def resolve(self, request):
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")
        return FieldResolutionResponse(
            value="A123",
            confidence=0.95,
            insufficient_evidence=False,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            actual_cost_usd=0.01,
        )


def request(**changes):
    crop = b"crop-only-phi"
    values = {
        "request_id": "r1",
        "tenant_id": "t1",
        "document_id": "d1",
        "field_name": "member_id",
        "expected_type": "code",
        "crop_bytes": crop,
        "crop_sha256": hashlib.sha256(crop).hexdigest(),
    }
    values.update(changes)
    return FieldResolutionRequest(**values)


def policy(**changes):
    values = {
        "tenant_id": "t1",
        "enabled": True,
        "phi_external_processing_approved": True,
        "approved_regions": {"us-central1"},
        "allowed_models": {"gemini-2.5-flash-lite"},
        "daily_budget_usd": 1,
        "max_requests_per_minute": 5,
    }
    values.update(changes)
    return TenantAIPolicy(**values)


@pytest.mark.asyncio
async def test_phi_approval_region_and_allowlist_are_enforced_before_call():
    provider = Provider()
    gateway = AIGateway({"t1": policy(phi_external_processing_approved=False)})
    with pytest.raises(GatewayPolicyError):
        await gateway.resolve(request(), provider, estimated_cost_usd=0.01)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_budget_and_rate_limits_prevent_provider_calls():
    provider = Provider()
    with pytest.raises(GatewayBudgetError):
        await AIGateway({"t1": policy(daily_budget_usd=0)}).resolve(
            request(), provider, estimated_cost_usd=0.01
        )
    gateway = AIGateway({"t1": policy(max_requests_per_minute=1)})
    await gateway.resolve(request(), provider, estimated_cost_usd=0.01)
    with pytest.raises(GatewayRateLimitError):
        await gateway.resolve(request(request_id="r2"), provider, estimated_cost_usd=0.01)


@pytest.mark.asyncio
async def test_audit_contains_hash_and_accounting_but_not_field_value_or_crop():
    audits = []
    result = await AIGateway({"t1": policy()}, audit_sink=audits.append).resolve(
        request(), Provider(), estimated_cost_usd=0.02, trace_id="trace-1"
    )
    assert result.value == "A123"
    dumped = audits[0].model_dump_json()
    assert "crop-only-phi" not in dumped
    assert "A123" not in dumped
    assert audits[0].actual_cost_usd == 0.01
    assert audits[0].trace_id == "trace-1"


@pytest.mark.asyncio
async def test_repeated_provider_failures_open_circuit():
    provider = Provider(fail=True)
    gateway = AIGateway({"t1": policy(max_retries=0)}, failure_threshold=2)
    for suffix in ("1", "2"):
        with pytest.raises(ConnectionError):
            await gateway.resolve(request(request_id=suffix), provider, estimated_cost_usd=0)
    with pytest.raises(GatewayCircuitOpenError):
        await gateway.resolve(request(request_id="3"), provider, estimated_cost_usd=0)
    assert provider.calls == 2
