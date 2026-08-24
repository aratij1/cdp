from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from packages.domain.common import DomainModel
from packages.roi_resolution import ROIResolutionMode


class PageZone(StrEnum):
    ANY = "ANY"
    UPPER_LEFT = "UPPER_LEFT"
    UPPER_MIDDLE = "UPPER_MIDDLE"
    UPPER_RIGHT = "UPPER_RIGHT"
    MIDDLE = "MIDDLE"
    LOWER_LEFT = "LOWER_LEFT"
    LOWER_MIDDLE = "LOWER_MIDDLE"
    LOWER_RIGHT = "LOWER_RIGHT"


class LocalizationStage(StrEnum):
    ANCHOR_FOUND = "ANCHOR_FOUND"
    REGION_PROPOSED = "REGION_PROPOSED"
    REGION_GEOMETRY_VALIDATED = "REGION_GEOMETRY_VALIDATED"
    VALUE_SPAN_DETECTED = "VALUE_SPAN_DETECTED"
    VALUE_SEMANTICALLY_VALIDATED = "VALUE_SEMANTICALLY_VALIDATED"
    STRUCTURALLY_RESOLVED = "STRUCTURALLY_RESOLVED"
    UNRESOLVED = "UNRESOLVED"


class LocalizationCandidate(DomainModel):
    candidate_id: str
    bbox: tuple[int, int, int, int]
    region_source: str
    token_ids: tuple[str, ...] = ()
    observed_text: str | None = None
    geometry_confidence: float = Field(ge=0, le=1)
    span_confidence: float | None = Field(default=None, ge=0, le=1)
    semantic_confidence: float | None = Field(default=None, ge=0, le=1)
    template_confidence: float | None = Field(default=None, ge=0, le=1)
    cross_field_confidence: float | None = Field(default=None, ge=0, le=1)
    score: float = Field(ge=0, le=1)
    candidate_region_hash: str
    reason_codes: tuple[str, ...] = ()


class FieldRelationship(DomainModel):
    relation: str
    x0_offset: float
    y0_offset: float
    x1_offset: float
    y1_offset: float


class FieldDefinition(DomainModel):
    field_name: str
    form_family: str
    aliases: tuple[str, ...]
    page_zone: PageZone = PageZone.ANY
    relationships: tuple[FieldRelationship, ...]
    neighbor_fields: tuple[str, ...] = ()
    negative_labels: tuple[str, ...] = ()
    datatype: str
    blocking: bool = False
    criticality: str = "HIGH"
    secondary_ocr_policy: str = "NONE"
    validation_policy: str = "NON_EMPTY"
    fuzzy_threshold: float = Field(default=.84, ge=.7, le=1)
    definition_version: str


class FieldLocationEvidence(DomainModel):
    field_name: str
    form_family: str
    bbox: tuple[int, int, int, int] | None = None
    method: ROIResolutionMode = ROIResolutionMode.UNRESOLVED
    confidence: float = Field(ge=0, le=1)
    anchor_ids: tuple[str, ...] = ()
    structure_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    locator_version: str = "field-locator-v1"
    document_id: str | None = None
    page_id: str | None = None
    stage: LocalizationStage = LocalizationStage.UNRESOLVED
    anchor_text: str | None = None
    anchor_bbox: tuple[int, int, int, int] | None = None
    anchor_confidence: float | None = Field(default=None, ge=0, le=1)
    region_source: str | None = None
    geometry_confidence: float | None = Field(default=None, ge=0, le=1)
    span_confidence: float | None = Field(default=None, ge=0, le=1)
    semantic_confidence: float | None = Field(default=None, ge=0, le=1)
    neighboring_anchors: tuple[str, ...] = ()
    structural_region_id: str | None = None
    template_id: str | None = None
    template_registration_confidence: float | None = Field(default=None, ge=0, le=1)
    candidate_region_hash: str | None = None
    selected_candidate_id: str | None = None
    candidates: tuple[LocalizationCandidate, ...] = ()
    wrong_crop_suspected: bool = False

    @model_validator(mode="after")
    def bbox_contract(self):
        if (self.method != ROIResolutionMode.UNRESOLVED and
                (self.bbox is None or self.bbox[2] <= self.bbox[0] or
                 self.bbox[3] <= self.bbox[1])):
            raise ValueError("resolved field location requires a positive bbox")
        return self
