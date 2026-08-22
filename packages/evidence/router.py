from __future__ import annotations

from dataclasses import dataclass


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
    _actions = {
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
        opportunities = [EvidenceOpportunity(item, *self._actions[item]) for item in missing_classes if item in self._actions]
        if not opportunities:
            return EvidenceOpportunity("E8", *self._actions["E8"])
        return max(opportunities, key=lambda item: item.utility)
