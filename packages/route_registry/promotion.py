from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field

from packages.domain.common import DomainModel
from packages.production_readiness_gate import ReadinessDecision
from packages.route_registry.models import RouteLifecycle


class RoutePromotionEvidence(DomainModel):
    route_id: str
    current_status: RouteLifecycle
    independent_holdout_frozen: bool = False
    holdout_samples: int = Field(default=0, ge=0)
    holdout_accuracy: float | None = Field(default=None, ge=0, le=1)
    agreement_precision: float | None = Field(default=None, ge=0, le=1)
    critical_false_agreements: int | None = Field(default=None, ge=0)
    mean_latency_ms: float | None = Field(default=None, ge=0)
    cost_per_call_usd: float | None = Field(default=None, ge=0)
    runtime_shadow_samples: int = Field(default=0, ge=0)
    operational_reliability: float | None = Field(default=None, ge=0, le=1)


class RoutePromotionResult(DomainModel):
    route_id: str
    decision: ReadinessDecision
    gates: dict[str, bool]
    blocking_reasons: list[str]


class RoutePromotionGate:
    def __init__(self, targets: dict) -> None:
        self.targets = targets

    @classmethod
    def load(
        cls, path: str | Path = "config/production_holdout_policy.yaml",
    ) -> "RoutePromotionGate":
        return cls(yaml.safe_load(Path(path).read_text("utf-8"))["route_promotion_targets"])

    def evaluate(self, evidence: RoutePromotionEvidence) -> RoutePromotionResult:
        t = self.targets
        gates = {
            "independent_holdout": evidence.independent_holdout_frozen,
            "sample_size": evidence.holdout_samples >= t["minimum_holdout_samples"],
            "accuracy": evidence.holdout_accuracy is not None and evidence.holdout_accuracy >= t["minimum_holdout_accuracy"],
            "agreement_precision": evidence.agreement_precision is not None and evidence.agreement_precision >= t["minimum_agreement_precision"],
            "critical_false_agreements": evidence.critical_false_agreements is not None and evidence.critical_false_agreements <= t["maximum_critical_false_agreements"],
            "latency": evidence.mean_latency_ms is not None and evidence.mean_latency_ms <= t["maximum_mean_latency_ms"],
            "cost": evidence.cost_per_call_usd is not None and evidence.cost_per_call_usd <= t["maximum_cost_per_call_usd"],
        }
        unsafe = (
            evidence.critical_false_agreements is not None
            and evidence.critical_false_agreements > t["maximum_critical_false_agreements"]
        )
        if unsafe:
            decision = ReadinessDecision.REJECT
        elif not gates["independent_holdout"] or not gates["sample_size"]:
            decision = ReadinessDecision.NEEDS_MORE_DATA
        elif not all(gates.values()):
            decision = ReadinessDecision.REJECT
        elif evidence.current_status is RouteLifecycle.EVALUATION_ONLY:
            decision = ReadinessDecision.PROMOTE_TO_SHADOW
        elif evidence.current_status is RouteLifecycle.SHADOW:
            shadow_ok = (
                evidence.runtime_shadow_samples >= t["minimum_runtime_shadow_samples"]
                and evidence.operational_reliability is not None
                and evidence.operational_reliability >= t["minimum_operational_reliability"]
            )
            gates["runtime_shadow_sample"] = (
                evidence.runtime_shadow_samples >= t["minimum_runtime_shadow_samples"]
            )
            gates["operational_reliability"] = (
                evidence.operational_reliability is not None
                and evidence.operational_reliability >= t["minimum_operational_reliability"]
            )
            decision = (
                ReadinessDecision.PROMOTE_TO_PRODUCTION
                if shadow_ok else ReadinessDecision.NEEDS_MORE_DATA
            )
        else:
            decision = ReadinessDecision.NEEDS_MORE_DATA
        return RoutePromotionResult(
            route_id=evidence.route_id,
            decision=decision,
            gates=gates,
            blocking_reasons=[name.upper() for name, passed in gates.items() if not passed],
        )
