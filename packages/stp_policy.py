"""Fail-closed claim-level straight-through-processing policy."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from packages.criticality import CriticalityLevel
from packages.claim_decision import (
    ClaimDecisionContext,
    ClaimDecisionService,
    ClaimDisposition,
)
from packages.evidence.models import EvidenceClass, EvidenceItem, FieldEvidenceBundle
from packages.evidence_decision import FieldDecision, FieldDisposition, NextAction

DEFAULT_STP_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "safe_stp_policy.yaml"


class STPLevel(StrEnum):
    STP_SAFE = "STP_SAFE"
    STP_STANDARD = "STP_STANDARD"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class FieldSTPEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_name: str
    criticality: CriticalityLevel
    required: bool = False
    resolved: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    evidence_policy_satisfied: bool = False
    independently_verified: bool = False
    validation_passed: bool = False
    reference_verified: bool = False


class ClaimSTPContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    form_type: str
    fields: list[FieldSTPEvidence]
    registration_confidence: float = Field(ge=0, le=1)
    page_classification_confidence: float = Field(ge=0, le=1)
    wrong_page_check_passed: bool
    wrong_crop_check_passed: bool
    mandatory_validation_results: dict[str, bool] = Field(default_factory=dict)
    unresolved_contradiction: bool = False
    document_valid: bool = True
    process_valid: bool = True
    service_lines_valid: bool = True
    open_review_tasks: int = Field(default=0, ge=0)


class STPDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: STPLevel
    claim_quality: float = Field(ge=0, le=1)
    reason_codes: list[str]
    minimum_critical_confidence: float = Field(ge=0, le=1)
    required_field_completeness: float = Field(ge=0, le=1)
    policy_version: str


class SafeSTPPolicy:
    """Compatibility adapter; ClaimDecisionService remains the disposition authority."""

    def __init__(self, config: dict, decision_service: ClaimDecisionService | None = None) -> None:
        self.config = config
        self.decision_service = decision_service or ClaimDecisionService.load()

    @classmethod
    def load(cls, path: str | Path = DEFAULT_STP_POLICY_PATH) -> "SafeSTPPolicy":
        return cls(yaml.safe_load(Path(path).read_text("utf-8")))

    def evaluate(self, context: ClaimSTPContext) -> STPDecision:
        required = [field for field in context.fields if field.required]
        critical = [field for field in context.fields if field.criticality in {
            CriticalityLevel.C2, CriticalityLevel.C3
        }]
        completeness = (
            sum(field.resolved for field in required) / len(required) if required else 0.0
        )
        min_critical = min((field.confidence for field in critical), default=0.0)
        reference_factor = min(
            (1.0 if field.reference_verified or field.independently_verified else field.confidence
             for field in critical), default=0.0
        )
        quality = min(
            completeness,
            min_critical,
            context.registration_confidence,
            context.page_classification_confidence,
            reference_factor,
        )
        reasons: list[str] = []
        if not context.document_valid:
            reasons.append("INVALID_DOCUMENT")
        if not context.process_valid:
            reasons.append("INVALID_PROCESS")
        if not context.wrong_page_check_passed:
            reasons.append("WRONG_PAGE_CHECK_FAILED")
        if not context.wrong_crop_check_passed:
            reasons.append("WRONG_CROP_CHECK_FAILED")
        if not required:
            reasons.append("REQUIRED_FIELD_POLICY_EMPTY")
        if completeness < 1:
            reasons.append("REQUIRED_FIELDS_UNRESOLVED")
        if not critical:
            reasons.append("CRITICAL_FIELD_POLICY_EMPTY")
        thresholds = self.config["field_confidence_thresholds"]
        for field in critical:
            if not field.resolved:
                reasons.append(f"CRITICAL_FIELD_UNRESOLVED:{field.field_name}")
            if not field.evidence_policy_satisfied:
                reasons.append(f"CRITICAL_EVIDENCE_POLICY_FAILED:{field.field_name}")
            if not field.validation_passed:
                reasons.append(f"CRITICAL_VALIDATION_FAILED:{field.field_name}")
            if field.confidence < float(thresholds[field.criticality.value]):
                reasons.append(f"CRITICAL_CONFIDENCE_FAILED:{field.field_name}")
        if context.unresolved_contradiction:
            reasons.append("UNRESOLVED_CONTRADICTION")
        if context.registration_confidence < float(self.config["minimum_registration_confidence"]):
            reasons.append("REGISTRATION_CONFIDENCE_FAILED")
        if context.page_classification_confidence < float(self.config["minimum_page_classification_confidence"]):
            reasons.append("PAGE_CLASSIFICATION_CONFIDENCE_FAILED")
        if not context.service_lines_valid:
            reasons.append("SERVICE_LINES_INVALID")
        if not context.mandatory_validation_results or not all(context.mandatory_validation_results.values()):
            reasons.append("MANDATORY_VALIDATION_FAILED")
        field_decisions = []
        for field in context.fields:
            threshold = float(thresholds.get(field.criticality.value, 1.0))
            accepted = (
                field.resolved
                and field.evidence_policy_satisfied
                and field.validation_passed
                and field.confidence >= threshold
            )
            independently_supported = field.independently_verified or field.reference_verified
            bundle = (
                FieldEvidenceBundle(
                    field_name=field.field_name,
                    evidence_items=[EvidenceItem(
                        evidence_class=EvidenceClass.E5 if field.reference_verified else EvidenceClass.E2,
                        evidence_type=(
                            "REFERENCE_CONFIRMED" if field.reference_verified
                            else "INDEPENDENT_VERIFICATION"
                        ),
                        evidence_family="legacy-stp-adapter",
                        source="SafeSTPPolicy-compatibility",
                        authoritative=field.reference_verified,
                        independent=field.independently_verified,
                    )],
                    policy_id=f"legacy:{field.field_name}",
                    policy_version=str(self.config["version"]),
                )
                if (
                    accepted
                    and independently_supported
                    and field.criticality is CriticalityLevel.C3
                ) else None
            )
            blocks = field.required or field.criticality in {
                CriticalityLevel.C2, CriticalityLevel.C3,
            }
            field_decisions.append(FieldDecision(
                field_name=field.field_name,
                disposition=(
                    FieldDisposition.AUTO_ACCEPTED
                    if accepted else FieldDisposition.HUMAN_REVIEW_REQUIRED
                ),
                calibrated_probability=field.confidence,
                next_action=NextAction.NONE if accepted else NextAction.HUMAN_REVIEW,
                policy_version=str(self.config["version"]),
                criticality=field.criticality,
                required=field.required,
                blocks_stp=blocks,
                requires_review_when_unresolved=blocks,
                evidence_bundle=bundle,
            ))

        global_review_reasons = []
        if not required:
            global_review_reasons.append("REQUIRED_FIELD_POLICY_EMPTY")
        if not critical:
            global_review_reasons.append("CRITICAL_FIELD_POLICY_EMPTY")
        if context.registration_confidence < float(self.config["minimum_registration_confidence"]):
            global_review_reasons.append("REGISTRATION_CONFIDENCE_FAILED")
        if context.page_classification_confidence < float(self.config["minimum_page_classification_confidence"]):
            global_review_reasons.append("PAGE_CLASSIFICATION_CONFIDENCE_FAILED")
        if not context.service_lines_valid:
            global_review_reasons.append("SERVICE_LINES_INVALID")
        if not context.mandatory_validation_results or not all(context.mandatory_validation_results.values()):
            global_review_reasons.append("MANDATORY_VALIDATION_FAILED")
        if global_review_reasons:
            field_decisions.append(FieldDecision(
                field_name="__legacy_claim_gate__",
                disposition=FieldDisposition.HUMAN_REVIEW_REQUIRED,
                calibrated_probability=0,
                reason_codes=global_review_reasons,
                next_action=NextAction.HUMAN_REVIEW,
                policy_version=str(self.config["version"]),
                criticality=CriticalityLevel.C2,
                required=True,
                blocks_stp=True,
                requires_review_when_unresolved=True,
            ))

        contradictions = []
        if context.unresolved_contradiction:
            contradictions.append(EvidenceItem(
                evidence_class=EvidenceClass.E6,
                evidence_type="UNRESOLVED_CONTRADICTION",
                evidence_family="legacy-stp-adapter",
                source="SafeSTPPolicy-compatibility",
            ))
        canonical = self.decision_service.decide(ClaimDecisionContext(
            claim_id=context.document_id,
            document_family=context.form_type,
            field_decisions=field_decisions,
            contradictions=contradictions,
            policy_id=self.decision_service.policy_id,
            policy_version=self.decision_service.policy_version,
            document_integrity_valid=(
                context.document_valid
                and context.wrong_page_check_passed
                and context.wrong_crop_check_passed
            ),
            process_integrity_valid=context.process_valid,
            enforce_configured_required_fields=False,
        ))
        mapping = {
            ClaimDisposition.STP_SAFE: STPLevel.STP_SAFE,
            ClaimDisposition.STP_STANDARD: STPLevel.STP_STANDARD,
            ClaimDisposition.FIELD_REVIEW_REQUIRED: STPLevel.REVIEW_REQUIRED,
            ClaimDisposition.CLAIM_REVIEW_REQUIRED: STPLevel.REVIEW_REQUIRED,
            ClaimDisposition.DOCUMENT_REJECTED: STPLevel.REJECTED,
        }
        final_reasons = reasons or canonical.reason_codes
        if canonical.stp_eligible:
            final_reasons = ["ALL_POLICY_GATES_PASSED"]
        return self._decision(
            mapping[canonical.disposition], quality, final_reasons,
            min_critical, completeness,
        )

    def _decision(self, level, quality, reasons, minimum, completeness) -> STPDecision:
        return STPDecision(
            level=level, claim_quality=quality, reason_codes=list(dict.fromkeys(reasons)),
            minimum_critical_confidence=minimum,
            required_field_completeness=completeness,
            policy_version=str(self.config["version"]),
        )
