"""Bridge adaptive routing decisions to selective cloud execution."""

from __future__ import annotations

from dataclasses import dataclass

from packages.ai_gateway.contracts import FieldResolutionRequest
from packages.ai_gateway.selective_resolution import (
    SelectiveResolutionCoordinator,
    SelectiveResolutionResult,
)
from packages.policy_engine import (
    AdaptivePolicyEngine,
    DecisionContext,
    PolicyDecision,
)


@dataclass(frozen=True)
class ResolutionStep:
    decision: PolicyDecision
    resolution: SelectiveResolutionResult | None = None


class AdaptiveResolutionService:
    def __init__(
        self,
        policy_engine: AdaptivePolicyEngine,
        coordinator: SelectiveResolutionCoordinator,
    ) -> None:
        self._policy_engine = policy_engine
        self._coordinator = coordinator

    async def execute_next(
        self,
        context: DecisionContext,
        request: FieldResolutionRequest,
        *,
        trace_id: str | None = None,
    ) -> ResolutionStep:
        decision = self._policy_engine.decide(context)
        cloud_actions = {
            "TEXTRACT", "GEMINI_CHEAP", "GEMINI_STANDARD", "GEMINI_ADVANCED"
        }
        if decision.action.value not in cloud_actions:
            return ResolutionStep(decision=decision)
        resolution = await self._coordinator.resolve(
            decision.action,
            request,
            estimated_cost_usd=decision.estimated_cost_usd,
            trace_id=trace_id,
        )
        return ResolutionStep(decision=decision, resolution=resolution)
