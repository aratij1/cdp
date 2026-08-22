"""Fail-closed claim-level straight-through-processing policy."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from packages.criticality import CriticalityLevel

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
    def __init__(self, config: dict) -> None:
        self.config = config

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
        if reasons:
            return self._decision(STPLevel.REJECTED, quality, reasons, min_critical, completeness)

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
        if reasons:
            return self._decision(STPLevel.REVIEW_REQUIRED, quality, reasons, min_critical, completeness)

        c3_fields = [field for field in context.fields if field.criticality is CriticalityLevel.C3]
        safe = bool(c3_fields) and all(field.independently_verified for field in c3_fields)
        level = STPLevel.STP_SAFE if safe else STPLevel.STP_STANDARD
        return self._decision(level, quality, ["ALL_POLICY_GATES_PASSED"], min_critical, completeness)

    def _decision(self, level, quality, reasons, minimum, completeness) -> STPDecision:
        return STPDecision(
            level=level, claim_quality=quality, reason_codes=list(dict.fromkeys(reasons)),
            minimum_critical_confidence=minimum,
            required_field_completeness=completeness,
            policy_version=str(self.config["version"]),
        )
