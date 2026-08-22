from __future__ import annotations

from pydantic import Field

from packages.domain.common import DomainModel


class ImageQualityEvidence(DomainModel):
    blur_score: float = Field(ge=0)
    contrast: float = Field(ge=0, le=1)
    brightness: float = Field(ge=0, le=1)
    skew_degrees: float
    rotation_degrees: int
    noise_estimate: float = Field(ge=0, le=1)
    estimated_dpi: float | None = Field(default=None, gt=0)
    compression_artifact_estimate: float = Field(ge=0, le=1)
    edge_clipping: float = Field(ge=0, le=1)
    text_density: float = Field(ge=0, le=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    assessment_version: str = "iq-v1"
    quality_score: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
