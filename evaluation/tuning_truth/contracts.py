from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TruthStatus(StrEnum):
    PRESENT = "PRESENT"
    BLANK = "BLANK"
    ILLEGIBLE = "ILLEGIBLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNSUPPORTED = "UNSUPPORTED"


class ReviewStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class Visibility(StrEnum):
    FULL_VALUE_VISIBLE = "FULL_VALUE_VISIBLE"
    PARTIAL_VALUE = "PARTIAL_VALUE"
    ILLEGIBLE = "ILLEGIBLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNANNOTATED = "UNANNOTATED"


class NormalizedBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1)
    y2: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def positive_area(self):
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("bbox must have positive area")
        return self


class PixelBBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(gt=0)
    y2: int = Field(gt=0)

    @model_validator(mode="after")
    def positive_area(self):
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("bbox must have positive area")
        return self


class FieldTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_id: str
    form_family: str
    field_name: str
    truth_value: str = ""
    normalized_truth_value: str = ""
    required: bool
    criticality: str
    blocks_stp: bool
    truth_status: TruthStatus = TruthStatus.UNSUPPORTED
    review_status: ReviewStatus = ReviewStatus.UNVERIFIED
    preannotation_source: str | None = None
    reviewer_id: str | None = None


class FieldCropTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_id: str
    form_family: str
    field_name: str
    value_bbox: NormalizedBBox | None = None
    value_bbox_pixels: PixelBBox | None = None
    label_bbox: NormalizedBBox | None = None
    expected_text: str = ""
    visibility: Visibility = Visibility.UNANNOTATED
    multi_line: bool = False
    annotation_confidence: float = Field(default=0, ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.UNVERIFIED
    reviewer_id: str | None = None


class UB04ServiceLineRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(ge=1)
    bbox: NormalizedBBox
    bbox_pixels: PixelBBox | None = None
    revenue_code: str = ""
    description: str = ""
    hcpcs: str = ""
    service_date: str = ""
    units: str = ""
    charge: str = ""


class UB04ServiceLineTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    page_id: str
    form_family: str = "UB04"
    rows: list[UB04ServiceLineRow] = Field(default_factory=list)
    expected_row_count: int = Field(default=0, ge=0)
    total_charge: str = ""
    review_status: ReviewStatus = ReviewStatus.UNVERIFIED
    reviewer_id: str | None = None

    @model_validator(mode="after")
    def row_contract(self):
        indexes = [row.row_index for row in self.rows]
        if len(indexes) != len(set(indexes)):
            raise ValueError("UB row indexes must be unique")
        if self.expected_row_count != len(self.rows):
            raise ValueError("expected_row_count must equal rows length")
        return self
