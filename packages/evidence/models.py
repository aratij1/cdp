from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import AliasChoices, Field, computed_field, model_validator

from packages.domain.common import DomainModel, new_id


class EvidenceClass(StrEnum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"
    E5 = "E5"
    E6 = "E6"
    E7 = "E7"
    E8 = "E8"


class StructuralLocalizationType(StrEnum):
    TEMPLATE_REGISTRATION_CONFIRMED = "TEMPLATE_REGISTRATION_CONFIRMED"
    ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED = "ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED"
    STRUCTURAL_LAYOUT_CONFIRMED = "STRUCTURAL_LAYOUT_CONFIRMED"
    UB_ROW_COLUMN_GEOMETRY_CONFIRMED = "UB_ROW_COLUMN_GEOMETRY_CONFIRMED"
    CHECKBOX_GEOMETRY_CONFIRMED = "CHECKBOX_GEOMETRY_CONFIRMED"


class StructuralLocalizationEvidence(DomainModel):
    """Qualified E3 evidence; an extraction mode alone is never confirmation."""

    evidence_type: StructuralLocalizationType
    confidence: float = Field(ge=0, le=1)
    confirmed: bool = False
    reason_codes: tuple[str, ...] = ()
    source: str
    version: str = "structural-localization-evidence-v1"
    field_name: str | None = None
    field_bbox: tuple[float, float, float, float] | None = None
    localization_mode: str | None = None
    anchor_id: str | None = None
    anchor_confidence: float | None = Field(default=None, ge=0, le=1)
    neighbor_evidence: tuple[str, ...] = ()
    positive_bounded_roi: bool | None = None
    geometry_valid: bool | None = None
    registration_compatible: bool | None = None

    @model_validator(mode="after")
    def confirmed_evidence_has_measurable_support(self):
        if self.confirmed and (self.confidence < 0.80 or not self.reason_codes):
            raise ValueError("CONFIRMED_STRUCTURAL_LOCALIZATION_REQUIRES_MEASURED_SUPPORT")
        return self


class EvidenceItem(DomainModel):
    evidence_id: UUID = Field(default_factory=new_id)
    evidence_class: EvidenceClass
    evidence_type: str
    evidence_family: str
    source: str
    value: str | None = None
    supports_candidate_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    independent: bool = False
    authoritative: bool = False
    deterministic: bool = False
    version: str | None = None
    metadata: dict = Field(default_factory=dict)


class FieldEvidenceBundle(DomainModel):
    field_name: str
    route_id: str | None = None
    route_status: str | None = None
    route_mode: str | None = None
    rejected_route_ids: list[str] = Field(default_factory=list)
    candidate_value: str | None = None
    selected_candidate_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(
        default_factory=list,
        validation_alias=AliasChoices("evidence_items", "items"),
    )
    contradictions: list[EvidenceItem] = Field(default_factory=list)
    missing_evidence_classes: set[EvidenceClass] = Field(default_factory=set)
    policy_id: str = "unresolved"
    policy_version: str = "unknown"

    @model_validator(mode="before")
    @classmethod
    def ignore_serialized_computed_fields(cls, value):
        """Allow lossless model_dump/model_validate event round trips."""
        if isinstance(value, dict) and "available_evidence_classes" in value:
            value = dict(value)
            value.pop("available_evidence_classes", None)
        return value

    @property
    def available_classes(self) -> set[EvidenceClass]:
        return {
            item.evidence_class
            for item in self.evidence_items
            if item.evidence_class != EvidenceClass.E0
        }

    @property
    def independent_families(self) -> set[str]:
        return {item.evidence_family for item in self.evidence_items if item.independent}

    @property
    def items(self) -> list[EvidenceItem]:
        """Compatibility alias for persisted v1 bundle consumers."""
        return self.evidence_items

    @computed_field
    @property
    def available_evidence_classes(self) -> set[EvidenceClass]:
        return self.available_classes


# Compatibility for persisted v1 payloads and existing callers.
EvidenceBundle = FieldEvidenceBundle
