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

    @model_validator(mode="after")
    def bbox_contract(self):
        if (self.method != ROIResolutionMode.UNRESOLVED and
                (self.bbox is None or self.bbox[2] <= self.bbox[0] or
                 self.bbox[3] <= self.bbox[1])):
            raise ValueError("resolved field location requires a positive bbox")
        return self
