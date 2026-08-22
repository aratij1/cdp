"""Cost-aware Gemini escalation; responses remain candidates, never truth."""

from __future__ import annotations

from dataclasses import dataclass

from packages.ai_gateway.contracts import AIProvider, FieldResolutionResponse
from packages.criticality import CriticalityLevel


@dataclass(frozen=True)
class EscalationContext:
    criticality: CriticalityLevel
    confidence_gap: float
    remaining_budget_usd: float
    remaining_sla_ms: int


def next_provider(
    providers: list[AIProvider],
    attempted_models: set[str],
    context: EscalationContext,
) -> AIProvider | None:
    if context.remaining_budget_usd <= 0 or context.remaining_sla_ms <= 0:
        return None
    for provider in providers:
        if provider.model_name not in attempted_models:
            return provider
    return None


def evidence_sufficient(response: FieldResolutionResponse, context: EscalationContext) -> bool:
    if response.insufficient_evidence or response.value is None:
        return False
    thresholds = {
        CriticalityLevel.C0: 0.75,
        CriticalityLevel.C1: 0.85,
        CriticalityLevel.C2: 0.95,
        CriticalityLevel.C3: 1.01,
    }
    # C3 AI evidence always proceeds to deterministic reconciliation; AI
    # confidence alone never short-circuits the cascade into acceptance.
    return response.confidence >= thresholds[context.criticality]
