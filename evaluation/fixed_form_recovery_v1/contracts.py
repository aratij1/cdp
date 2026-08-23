from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from workers.page_detection.template_compatibility import TemplateCompatibilityEvidence


class RegistrationFailureReason(StrEnum):
    TEMPLATE_NOT_COMPATIBLE = "TEMPLATE_NOT_COMPATIBLE"
    TEMPLATE_LINEAGE_MISMATCH = "TEMPLATE_LINEAGE_MISMATCH"
    WRONG_TEMPLATE_ASSET = "WRONG_TEMPLATE_ASSET"
    TEMPLATE_VERSION_MISMATCH = "TEMPLATE_VERSION_MISMATCH"
    PAGE_DIMENSION_MISMATCH = "PAGE_DIMENSION_MISMATCH"
    ASPECT_RATIO_MISMATCH = "ASPECT_RATIO_MISMATCH"
    ORIENTATION_MISMATCH = "ORIENTATION_MISMATCH"
    INSUFFICIENT_KEYPOINTS_SOURCE = "INSUFFICIENT_KEYPOINTS_SOURCE"
    INSUFFICIENT_KEYPOINTS_TEMPLATE = "INSUFFICIENT_KEYPOINTS_TEMPLATE"
    INSUFFICIENT_MATCHES = "INSUFFICIENT_MATCHES"
    LOWE_FILTER_COLLAPSE = "LOWE_FILTER_COLLAPSE"
    RANSAC_INLIER_FAILURE = "RANSAC_INLIER_FAILURE"
    BAD_HOMOGRAPHY = "BAD_HOMOGRAPHY"
    REPROJECTION_ERROR_HIGH = "REPROJECTION_ERROR_HIGH"
    INVALID_TRANSFORMED_CORNERS = "INVALID_TRANSFORMED_CORNERS"
    COVERAGE_FAILURE = "COVERAGE_FAILURE"
    SCALE_FAILURE = "SCALE_FAILURE"
    PERSPECTIVE_FAILURE = "PERSPECTIVE_FAILURE"
    LINE_STRUCTURE_MISMATCH = "LINE_STRUCTURE_MISMATCH"
    ANCHOR_MISMATCH = "ANCHOR_MISMATCH"
    INPUT_PREPROCESSING_MISMATCH = "INPUT_PREPROCESSING_MISMATCH"
    REFERENCE_ASSET_QUALITY = "REFERENCE_ASSET_QUALITY"
    UNKNOWN = "UNKNOWN"


class RegistrationForensicRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    truth_family: str
    nominated_family: str
    source_dataset: str
    template_attempted: str
    source_dimensions: tuple[int, int]
    template_dimensions: tuple[int, int]
    aspect_ratio: float
    template_aspect_ratio: float
    image_dpi_estimate: float | None = None
    orientation: str
    cheap_alignment_status: str
    keypoints_source: int = 0
    keypoints_template: int = 0
    knn_matches: int = 0
    good_matches: int = 0
    lowe_ratio_survivors: int = 0
    ransac_inliers: int = 0
    inlier_ratio: float = Field(default=0, ge=0, le=1)
    homography_returned: bool = False
    homography_determinant: float | None = None
    reprojection_error: float | None = None
    corner_validity: bool | None = None
    coverage: float | None = None
    scale: float | None = None
    rotation: float | None = None
    perspective_distortion: float | None = None
    compatibility: TemplateCompatibilityEvidence
    sift_attempted: bool = False
    success: bool
    final_rejection_reason: RegistrationFailureReason | None = None
    raw_rejection_reason: str | None = None
    latency_ms: float = Field(ge=0)


class CropQualityClass(StrEnum):
    CORRECT_TEXT_FULLY_VISIBLE = "CORRECT_TEXT_FULLY_VISIBLE"
    CORRECT_TEXT_PARTIAL = "CORRECT_TEXT_PARTIAL"
    WRONG_FIELD = "WRONG_FIELD"
    LABEL_ONLY = "LABEL_ONLY"
    EMPTY = "EMPTY"
    MULTIPLE_FIELDS = "MULTIPLE_FIELDS"
    LABEL_VALUE_MIXED = "LABEL_VALUE_MIXED"
    NEIGHBOR_CONTAMINATION = "NEIGHBOR_CONTAMINATION"
    TABLE_GRID_ONLY = "TABLE_GRID_ONLY"
    UNKNOWN = "UNKNOWN"


class FieldSupportStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
