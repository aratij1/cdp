from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from packages.domain.common import DomainModel


class ExtractionFailureType(StrEnum):
    LOCALIZATION_WRONG = "LOCALIZATION_WRONG"
    UNDER_CROP = "UNDER_CROP"
    OVER_CROP = "OVER_CROP"
    OCR_CHARACTER_ERROR = "OCR_CHARACTER_ERROR"
    OCR_WORD_ERROR = "OCR_WORD_ERROR"
    OCR_EMPTY = "OCR_EMPTY"
    MULTILINE_ASSEMBLY_ERROR = "MULTILINE_ASSEMBLY_ERROR"
    SPAN_SELECTION_ERROR = "SPAN_SELECTION_ERROR"
    NORMALIZATION_ERROR = "NORMALIZATION_ERROR"
    PARSING_ERROR = "PARSING_ERROR"
    CANDIDATE_RANKING_ERROR = "CANDIDATE_RANKING_ERROR"
    RECONCILIATION_ERROR = "RECONCILIATION_ERROR"
    DETERMINISTIC_REJECT_CORRECT_VALUE = "DETERMINISTIC_REJECT_CORRECT_VALUE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    TRUE_AMBIGUITY = "TRUE_AMBIGUITY"
    UNKNOWN = "UNKNOWN"


class SpanSelectionResult(DomainModel):
    raw_text: str
    selected_text: str
    rule_id: str
    confidence: float = Field(ge=0, le=1)
    candidate_spans: tuple[str, ...] = ()
    source_lines: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


class CandidateObservation(DomainModel):
    candidate_id: str
    raw_text: str
    selected_text: str
    normalized_value: str | None = None
    engine: str
    preprocessing_profile: str
    ocr_confidence: float = Field(ge=0, le=1)
    localization_confidence: float = Field(ge=0, le=1)
    semantic_confidence: float = Field(ge=0, le=1)
    deterministic_valid: bool
    cross_field_confidence: float = Field(default=0, ge=0, le=1)
    engine_reliability: float = Field(default=.5, ge=0, le=1)
    preprocessing_reliability: float = Field(default=.5, ge=0, le=1)
    dependency_quality: float = Field(default=0, ge=0, le=1)


class CandidateRankingResult(DomainModel):
    selected_candidate_id: str | None = None
    selected_value: str | None = None
    score: float = Field(default=0, ge=0, le=1)
    ranked_candidate_ids: tuple[str, ...] = ()
    score_breakdown: dict[str, dict[str, float]] = Field(default_factory=dict)
    ranking_version: str
    reason_codes: tuple[str, ...] = ()


class WrongCropAssessment(DomainModel):
    risk: float = Field(ge=0, le=1)
    detected: bool
    threshold: float = Field(ge=0, le=1)
    signal_scores: dict[str, float]
    reason_codes: tuple[str, ...] = ()
    detector_version: str
