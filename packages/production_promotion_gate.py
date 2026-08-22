"""Final, evidence-backed production promotion gate for CDP vNext."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PromotionDecision(StrEnum):
    PROMOTABLE = "PROMOTABLE"
    BLOCKED = "BLOCKED"


class ProductionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frozen_release_integrity: bool = False
    full_suite_passed: bool = False
    unexplained_test_failures: int = Field(default=0, ge=0)
    independent_holdout_frozen: bool = False
    holdout_is_synthetic: bool = False
    holdout_documents: int = Field(default=0, ge=0)
    holdout_fields: int = Field(default=0, ge=0)
    overall_accuracy: float | None = Field(default=None, ge=0, le=1)
    critical_accuracy: float | None = Field(default=None, ge=0, le=1)
    critical_false_accept_rate: float | None = Field(default=None, ge=0, le=1)
    total_false_accept_rate: float | None = Field(default=None, ge=0, le=1)
    safe_stp_rate: float | None = Field(default=None, ge=0, le=1)
    load_test_passed: bool = False
    kubernetes_keda_test_passed: bool = False
    disaster_recovery_test_passed: bool = False
    security_assessment_passed: bool = False


class ProductionGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: PromotionDecision
    gates: dict[str, bool]
    blocking_reasons: list[str]
    policy_version: str


class ProductionPromotionGate:
    def __init__(self, config: dict) -> None:
        self.config = config

    @classmethod
    def load(cls, path: str | Path = "config/production_promotion_gate.yaml"):
        return cls(yaml.safe_load(Path(path).read_text("utf-8")))

    def evaluate(self, evidence: ProductionEvidence) -> ProductionGateResult:
        limits = self.config["requirements"]
        independent = evidence.independent_holdout_frozen and not evidence.holdout_is_synthetic
        gates = {
            "frozen_release_integrity": evidence.frozen_release_integrity,
            "zero_unexplained_test_failures": evidence.full_suite_passed and evidence.unexplained_test_failures == 0,
            "independent_non_synthetic_holdout": independent,
            "minimum_holdout_size": independent and evidence.holdout_documents >= limits["minimum_documents"]
                                    and evidence.holdout_fields >= limits["minimum_fields"],
            "overall_accuracy": evidence.overall_accuracy is not None and evidence.overall_accuracy >= limits["minimum_overall_accuracy"],
            "critical_accuracy": evidence.critical_accuracy is not None and evidence.critical_accuracy >= limits["minimum_critical_accuracy"],
            "critical_false_accept_rate": evidence.critical_false_accept_rate is not None and evidence.critical_false_accept_rate <= limits["maximum_critical_false_accept_rate"],
            "total_false_accept_rate": evidence.total_false_accept_rate is not None and evidence.total_false_accept_rate <= limits["maximum_total_false_accept_rate"],
            "safe_stp_measured": evidence.safe_stp_rate is not None,
            "load_test": evidence.load_test_passed,
            "kubernetes_keda": evidence.kubernetes_keda_test_passed,
            "disaster_recovery": evidence.disaster_recovery_test_passed,
            "security_assessment": evidence.security_assessment_passed,
        }
        reasons = [name.upper() for name, passed in gates.items() if not passed]
        return ProductionGateResult(
            decision=PromotionDecision.PROMOTABLE if all(gates.values()) else PromotionDecision.BLOCKED,
            gates=gates, blocking_reasons=reasons, policy_version=str(self.config["version"]),
        )
