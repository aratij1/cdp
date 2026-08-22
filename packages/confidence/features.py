"""Auditable evidence feature records used for confidence calibration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CalibrationFeatureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    split: str
    document_type: str
    field_name: str
    field_family: str
    criticality: str
    selected_engine: str
    rapidocr_confidence: float | None = Field(default=None, ge=0, le=1)
    paddle_confidence: float | None = Field(default=None, ge=0, le=1)
    tesseract_confidence: float | None = Field(default=None, ge=0, le=1)
    selected_confidence: float = Field(ge=0, le=1)
    engine_agreement_count: int = Field(ge=0)
    registration_confidence: float | None = Field(default=None, ge=0, le=1)
    image_quality_score: float | None = Field(default=None, ge=0, le=1)
    format_valid: bool
    reference_match_score: float | None = Field(default=None, ge=0, le=1)
    cross_field_consistency: bool | None = None
    preprocessing_profile: str
    label_contamination_detected: bool
    correct: bool
