"""Cost-ordered evidence acquisition for one field and one policy."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import Field

from packages.domain.common import DomainModel


class ReferenceSourceState(StrEnum):
    DISABLED = "DISABLED"
    TEST_FIXTURE = "TEST_FIXTURE"
    AUTHORIZED = "AUTHORIZED"


class EvidenceAcquisitionAction(StrEnum):
    ACCEPT = "ACCEPT"
    PROPAGATE_EXISTING_EVIDENCE = "PROPAGATE_EXISTING_EVIDENCE"
    CROP_RECOVERY = "CROP_RECOVERY"
    DETERMINISTIC_VALIDATION = "DETERMINISTIC_VALIDATION"
    CROSS_FIELD_RECONCILIATION = "CROSS_FIELD_RECONCILIATION"
    SECONDARY_OCR = "SECONDARY_OCR"
    REFERENCE_LOOKUP = "REFERENCE_LOOKUP"
    CLOUD_AI = "CLOUD_AI"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class EvidenceGapDecision(DomainModel):
    action: EvidenceAcquisitionAction
    target_evidence_class: str | None = None
    missing_evidence_classes: tuple[str, ...] = ()
    selected_requirement: tuple[str, ...] = ()
    confirmation_engine: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    estimated_cost_usd: float = Field(default=0, ge=0)
    estimated_latency_ms: int = Field(default=0, ge=0)


class EvidenceGapRouter:
    """Choose only the cheapest evidence that can complete a policy alternative."""

    _class_routes: ClassVar[dict[str, tuple[EvidenceAcquisitionAction, int, float]]] = {
        "E3": (EvidenceAcquisitionAction.CROP_RECOVERY, 120, .001),
        "E4": (EvidenceAcquisitionAction.DETERMINISTIC_VALIDATION, 5, .0001),
        "E6": (EvidenceAcquisitionAction.CROSS_FIELD_RECONCILIATION, 10, .0001),
        "E2": (EvidenceAcquisitionAction.SECONDARY_OCR, 180, .002),
        "E5": (EvidenceAcquisitionAction.REFERENCE_LOOKUP, 80, .001),
        "E7": (EvidenceAcquisitionAction.CLOUD_AI, 800, .02),
        "E8": (EvidenceAcquisitionAction.HUMAN_REVIEW, 60000, 1.0),
    }
    _priority: ClassVar[dict[str, int]] = {
        "E3": 0, "E4": 1, "E6": 2, "E2": 3, "E5": 4, "E7": 5, "E8": 6,
    }

    def route(
        self,
        *,
        available: set[str],
        requirements: tuple[frozenset[str], ...],
        propagatable: set[str] | None = None,
        reference_state: ReferenceSourceState = ReferenceSourceState.DISABLED,
        confirmation_engine: str | None = None,
    ) -> EvidenceGapDecision:
        if any(requirement <= available for requirement in requirements):
            return EvidenceGapDecision(
                action=EvidenceAcquisitionAction.ACCEPT,
                reason_codes=["EVIDENCE_POLICY_ALREADY_SATISFIED"],
            )
        propagatable = propagatable or set()
        alternatives: list[tuple[tuple[int, int, tuple[str, ...]], frozenset[str], set[str]]] = []
        for requirement in requirements:
            missing = set(requirement) - available
            if not missing:
                continue
            routable = set(missing)
            if "E5" in routable and reference_state is not ReferenceSourceState.AUTHORIZED:
                routable.remove("E5")
            if not routable:
                continue
            priorities = [self._priority.get(item, 99) for item in routable]
            alternatives.append(((min(priorities), len(missing), tuple(sorted(missing))), requirement, missing))
        if not alternatives:
            return EvidenceGapDecision(
                action=EvidenceAcquisitionAction.HUMAN_REVIEW,
                target_evidence_class="E8",
                missing_evidence_classes=("E8",),
                reason_codes=["NO_AUTHORIZED_AUTOMATED_EVIDENCE_ROUTE"],
                estimated_cost_usd=1.0,
                estimated_latency_ms=60000,
            )
        _, requirement, missing = min(alternatives, key=lambda item: item[0])
        existing = sorted(missing & propagatable, key=lambda item: self._priority.get(item, 99))
        if existing:
            target = existing[0]
            return EvidenceGapDecision(
                action=EvidenceAcquisitionAction.PROPAGATE_EXISTING_EVIDENCE,
                target_evidence_class=target,
                missing_evidence_classes=tuple(sorted(missing)),
                selected_requirement=tuple(sorted(requirement)),
                reason_codes=[f"{target}_EXISTS_UPSTREAM", "EVIDENCE_NOT_PROPAGATED"],
            )
        target = min(
            (item for item in missing if item != "E5" or reference_state is ReferenceSourceState.AUTHORIZED),
            key=lambda item: self._priority.get(item, 99),
        )
        action, latency, cost = self._class_routes.get(
            target, (EvidenceAcquisitionAction.HUMAN_REVIEW, 60000, 1.0)
        )
        reasons = [f"ACQUIRE_{target}", "CHEAPEST_POLICY_COMPLETING_EVIDENCE"]
        if target == "E2" and not confirmation_engine:
            action, latency, cost = EvidenceAcquisitionAction.HUMAN_REVIEW, 60000, 1.0
            reasons = ["NO_BENCHMARK_APPROVED_CONFIRMATION_ENGINE"]
        return EvidenceGapDecision(
            action=action,
            target_evidence_class=target,
            missing_evidence_classes=tuple(sorted(missing)),
            selected_requirement=tuple(sorted(requirement)),
            confirmation_engine=confirmation_engine if target == "E2" else None,
            reason_codes=reasons,
            estimated_cost_usd=cost,
            estimated_latency_ms=latency,
        )
