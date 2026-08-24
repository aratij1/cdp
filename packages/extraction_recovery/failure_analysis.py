from __future__ import annotations

from difflib import SequenceMatcher

from .contracts import ExtractionFailureType


def classify_extraction_failure(*, localization_outcome: str, raw_text: str,
                                selected_value: str | None, expected_value: str,
                                normalized_raw: str | None, oracle_contains_truth: bool,
                                span_contains_truth: bool) -> tuple[ExtractionFailureType, tuple[str, ...]]:
    if localization_outcome in {"WRONG_NEIGHBOR", "WRONG_REGION", "EMPTY_REGION"}:
        return ExtractionFailureType.LOCALIZATION_WRONG, (localization_outcome,)
    if localization_outcome == "UNDER_CROP":
        return ExtractionFailureType.UNDER_CROP, ()
    if not (raw_text or "").strip():
        return ExtractionFailureType.OCR_EMPTY, ()
    if oracle_contains_truth and selected_value != expected_value:
        return ExtractionFailureType.CANDIDATE_RANKING_ERROR, ("ORACLE_CANDIDATE_PRESENT",)
    if span_contains_truth and selected_value != expected_value:
        return ExtractionFailureType.SPAN_SELECTION_ERROR, ("RECOVERABLE_SEMANTIC_SPAN",)
    if normalized_raw == expected_value and selected_value != expected_value:
        return ExtractionFailureType.NORMALIZATION_ERROR, ("RAW_NORMALIZATION_WAS_CORRECT",)
    similarity = SequenceMatcher(None, selected_value or raw_text, expected_value).ratio()
    if similarity >= .70:
        return ExtractionFailureType.OCR_CHARACTER_ERROR, (f"SIMILARITY_{similarity:.3f}",)
    return ExtractionFailureType.OCR_WORD_ERROR, (f"SIMILARITY_{similarity:.3f}",)
