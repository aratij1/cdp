"""Phase 8.10 extraction recovery primitives."""

from .contracts import (
    CandidateObservation,
    CandidateRankingResult,
    ExtractionFailureType,
    SpanSelectionResult,
    WrongCropAssessment,
)
from .crop_recovery import bounded_expand_bbox
from .failure_analysis import classify_extraction_failure
from .ranking import CandidateScoringPolicy, rank_candidates
from .span_selection import select_field_span
from .wrong_crop import WrongCropDetector

__all__ = [
    "CandidateObservation",
    "CandidateRankingResult",
    "CandidateScoringPolicy",
    "ExtractionFailureType",
    "SpanSelectionResult",
    "WrongCropAssessment",
    "WrongCropDetector",
    "bounded_expand_bbox",
    "classify_extraction_failure",
    "rank_candidates",
    "select_field_span",
]
