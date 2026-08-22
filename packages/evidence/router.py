from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from packages.evidence_router import EvidenceGapRouter as PolicyEvidenceGapRouter


@dataclass(frozen=True)
class EvidenceOpportunity:
    missing_class: str
    action: str
    expected_gain: float
    estimated_cost: float
    estimated_latency_ms: int

    @property
    def utility(self) -> float:
        return self.expected_gain / max(self.estimated_cost + self.estimated_latency_ms / 1000, .001)


class EvidenceGapRouter:
    _actions: ClassVar[dict[str, tuple[str, float, float, int]]] = {
        "E1": ("PRIMARY_OCR", .35, .001, 100),
        "E2": ("SECONDARY_OCR", .60, .002, 180),
        "E3": ("CROP_RECOVERY", .70, .001, 120),
        "E4": ("DETERMINISTIC_VALIDATION", .85, .0001, 5),
        "E5": ("REFERENCE_LOOKUP", .90, .001, 80),
        "E6": ("CROSS_FIELD_RECONCILIATION", .80, .0001, 10),
        "E7": ("CLOUD_AI", .55, .02, 800),
        "E8": ("HUMAN_REVIEW", 1.0, 1.0, 60000),
    }

    def route(self, missing_classes: tuple[str, ...]) -> EvidenceOpportunity:
        """Compatibility adapter; new callers use packages.evidence_router directly."""
        requirements = (frozenset(missing_classes),) if missing_classes else ()
        decision = PolicyEvidenceGapRouter().route(
            available=set(), requirements=requirements, confirmation_engine="configured",
        )
        target = decision.target_evidence_class or "E8"
        action = decision.action.value
        if action == "ACCEPT":
            action = "ACCEPT"
        return EvidenceOpportunity(
            target, action, 1.0, decision.estimated_cost_usd,
            decision.estimated_latency_ms,
        )
