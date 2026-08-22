"""Strict, versioned schemas for labelled truth and extraction predictions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.claim_decision import ClaimDecision


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GroundTruthField(EvaluationModel):
    field_name: str
    expected_raw: str | None = None
    expected_normalized: str | None = None
    required: bool = False
    critical: bool = False


class GroundTruthDocument(EvaluationModel):
    document_id: str
    file_name: str
    form_type: Literal["CMS1500", "UB04", "UNSTRUCTURED"]
    image_quality_bucket: str = "unknown"
    split: Literal["calibration", "validation", "holdout"] = "holdout"
    fields: list[GroundTruthField]

    @model_validator(mode="after")
    def unique_fields(self) -> GroundTruthDocument:
        names = [field.field_name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate field names in document {self.document_id}")
        return self


class GroundTruthDataset(EvaluationModel):
    schema_version: str = "1.0"
    documents: list[GroundTruthDocument]

    @model_validator(mode="after")
    def unique_documents(self) -> GroundTruthDataset:
        ids = [document.document_id for document in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate document_id values")
        return self


class BoundingBoxValue(EvaluationModel):
    x: float
    y: float
    width: float
    height: float


class PredictedField(EvaluationModel):
    field_name: str
    raw_value: str | None = None
    normalized_value: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    calibrated_confidence: float | None = Field(default=None, ge=0, le=1)
    validation_result: str = "PENDING"
    extraction_method: str = "UNKNOWN"
    bounding_box: BoundingBoxValue | None = None
    crop_reference: str | None = None
    accepted: bool = False
    reviewed: bool = False
    fallback_used: bool = False
    before_fallback_value: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PredictionDocument(EvaluationModel):
    document_id: str
    fields: list[PredictedField]
    claim_decision: ClaimDecision | None = None

    @model_validator(mode="after")
    def unique_fields(self) -> PredictionDocument:
        names = [field.field_name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate predicted field names in document {self.document_id}")
        return self


class PredictionDataset(EvaluationModel):
    schema_version: str = "1.0"
    documents: list[PredictionDocument]
