"""Auditable page-registration evidence contracts."""

from __future__ import annotations

from pydantic import Field

from packages.domain.common import DomainModel


class RegistrationEvidence(DomainModel):
    template_id: str | None = None
    algorithm: str
    keypoints_source: int = 0
    keypoints_template: int = 0
    candidate_match_count: int = 0
    good_matches: int = 0
    inlier_count: int = 0
    inlier_ratio: float = Field(default=0.0, ge=0, le=1)
    reprojection_error: float | None = Field(default=None, ge=0)
    coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    template_coverage: float | None = Field(default=None, ge=0, le=1)
    # A degenerate homography can legitimately produce a zero scale during
    # forensics.  It must be representable as rejected evidence rather than
    # crashing before the SCALE_FAILURE policy can classify it.
    scale_change: float | None = Field(default=None, ge=0)
    rotation_degrees: float | None = None
    perspective_distortion: float | None = Field(default=None, ge=0)
    corner_validity: bool | None = None
    homography_quality: float = Field(default=0.0, ge=0, le=1)
    alignment_confidence: float = Field(default=0.0, ge=0, le=1)
    transform_matrix: list[list[float]] | None = None
    accepted: bool
    rejection_reason: str | None = None
    processing_time_ms: float = Field(default=0.0, ge=0)
