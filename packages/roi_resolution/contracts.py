from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from packages.domain.common import DomainModel
from packages.extraction_geometry.contracts import ExtractionGeometryDecision


class ROIResolutionMode(StrEnum):
    FIXED_REGISTERED = "FIXED_REGISTERED"
    ANCHOR_RELATIVE = "ANCHOR_RELATIVE"
    STRUCTURAL_REGION = "STRUCTURAL_REGION"
    UNRESOLVED = "UNRESOLVED"


class ObservedAnchor(DomainModel):
    anchor_id: str
    bbox: tuple[int, int, int, int]
    confidence: float = Field(ge=0, le=1)


class AnchorRelativeContract(DomainModel):
    """A field-local spatial contract, expressed relative to one anchor.

    Offsets are normalized by page width/height, so this mode never treats a
    family label as permission to reuse absolute template coordinates.
    """

    field_name: str
    anchor_id: str
    x0_offset: float
    y0_offset: float
    x1_offset: float
    y1_offset: float
    min_anchor_confidence: float = Field(default=0.85, ge=0, le=1)
    contract_version: str = "anchor-relative-contract-v1"


class ROIResolutionRequest(DomainModel):
    field_name: str
    page_width: int = Field(gt=0)
    page_height: int = Field(gt=0)
    geometry: ExtractionGeometryDecision
    fixed_region: tuple[int, int, int, int] | None = None
    anchor_contract: AnchorRelativeContract | None = None
    observed_anchors: tuple[ObservedAnchor, ...] = ()
    structural_region: tuple[int, int, int, int] | None = None


class ROIResolutionResult(DomainModel):
    field_name: str
    mode: ROIResolutionMode
    bbox: tuple[int, int, int, int] | None = None
    field_structural_confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: tuple[str, ...] = ()
    resolver_version: str = "roi-resolver-v1"

    @model_validator(mode="after")
    def resolved_modes_need_valid_boxes(self):
        if self.mode != ROIResolutionMode.UNRESOLVED:
            if self.bbox is None:
                raise ValueError("RESOLVED_ROI_REQUIRES_BBOX")
            x0, y0, x1, y1 = self.bbox
            if x1 <= x0 or y1 <= y0:
                raise ValueError("RESOLVED_ROI_REQUIRES_POSITIVE_AREA")
        return self
