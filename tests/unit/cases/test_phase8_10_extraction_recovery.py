from __future__ import annotations

import pytest
from PIL import Image

import evaluation.phase8_10_extraction_recovery as phase810
from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.evidence_dependency import DependencyRelation, EvidenceDependencyService
from packages.extraction_recovery import (
    CandidateObservation,
    CandidateScoringPolicy,
    ExtractionFailureType,
    WrongCropDetector,
    bounded_expand_bbox,
    classify_extraction_failure,
    rank_candidates,
    select_field_span,
)
from packages.field_localization import FieldLocationEvidence, LocalizationStage
from packages.local_evidence_cascade import decide_local_candidate
from packages.ocr import OCRCandidate, OCRExecutionService, OCRRequest, OCRResult
from packages.ocr.preprocessing import PreprocessingRegistry
from packages.ocr.provenance import EvidenceProvenance
from packages.roi_resolution import ROIResolutionMode


def _location(**updates) -> FieldLocationEvidence:
    values = {
        "field_name": "patient_dob", "form_family": "CMS1500",
        "bbox": (10, 10, 100, 40), "method": ROIResolutionMode.ANCHOR_RELATIVE,
        "confidence": .85, "stage": LocalizationStage.VALUE_SEMANTICALLY_VALIDATED,
        "region_source": "ANCHOR_BELOW_TOKEN_SPAN", "geometry_confidence": .85,
    }
    values.update(updates)
    return FieldLocationEvidence(**values)


def test_correct_localization_ocr_error_has_exactly_one_primary_failure():
    failure, secondary = classify_extraction_failure(
        localization_outcome="VALUE_CONTAINED", raw_text="01/02/198O",
        selected_value="01/02/198O", expected_value="01/02/1980",
        normalized_raw="01/02/198O", oracle_contains_truth=False,
        span_contains_truth=False,
    )
    assert failure is ExtractionFailureType.OCR_CHARACTER_ERROR
    assert len(secondary) == 1


def test_normalization_regression_is_separate_from_ocr_error():
    failure, _ = classify_extraction_failure(
        localization_outcome="VALUE_CONTAINED", raw_text="01/02/1980",
        selected_value="1980-02-01", expected_value="1980-01-02",
        normalized_raw="1980-01-02", oracle_contains_truth=False,
        span_contains_truth=False,
    )
    assert failure is ExtractionFailureType.NORMALIZATION_ERROR


def test_correct_candidate_present_but_ranking_wrong_is_measured():
    failure, reasons = classify_extraction_failure(
        localization_outcome="OVER_CROP", raw_text="WRONG", selected_value="WRONG",
        expected_value="RIGHT", normalized_raw="WRONG", oracle_contains_truth=True,
        span_contains_truth=False,
    )
    assert failure is ExtractionFailureType.CANDIDATE_RANKING_ERROR
    assert "ORACLE_CANDIDATE_PRESENT" in reasons


def test_candidate_ranking_prefers_deterministically_valid_candidate():
    policy = CandidateScoringPolicy.load()
    invalid = CandidateObservation(
        candidate_id="high-ocr-invalid", raw_text="NPI", selected_text="NPI",
        engine="rapidocr", preprocessing_profile="PAGE_OBSERVATION",
        ocr_confidence=.99, localization_confidence=.9, semantic_confidence=.1,
        deterministic_valid=False,
    )
    valid = CandidateObservation(
        candidate_id="valid", raw_text="123.45", selected_text="123.45",
        normalized_value="123.45", engine="rapidocr",
        preprocessing_profile="CURRENCY_DECIMAL_V2", ocr_confidence=.80,
        localization_confidence=.9, semantic_confidence=1,
        deterministic_valid=True,
    )
    assert rank_candidates([invalid, valid], policy).selected_candidate_id == "valid"


def test_under_crop_expansion_is_bounded_and_signal_gated():
    bbox = (10, 10, 90, 30)
    assert bounded_expand_bbox(bbox, (100, 100), edge_truncated=False) == bbox
    assert bounded_expand_bbox(bbox, (100, 100), edge_truncated=True) == (9, 9, 91, 31)


def test_over_crop_span_selection_preserves_only_observed_date():
    selected = select_field_span("PATIENT DOB: 01/02/1980 SEX: F", "DATE", "patient_dob")
    assert selected.selected_text == "01/02/1980"
    assert "FIELD_SEMANTIC_SPAN" in selected.reason_codes


def test_multifield_currency_crop_selects_last_semantic_amount():
    selected = select_field_span("UNITS 25000 TOTAL CHARGE 3106.06", "CURRENCY", "total_charge")
    assert selected.selected_text == "3106.06"


def test_member_and_relationship_spans_remove_neighbor_labels():
    assert select_field_span("MEMBERID XX G18-0001006", "ALPHANUMERIC_ID", "member_id").selected_text == "G18-0001006"
    assert select_field_span("RELATIONSHIP CISELF", "CHECKBOX", "relationship").selected_text == "SELF"


def test_valid_looking_wrong_neighbor_signal_is_detected():
    assessment = WrongCropDetector().assess(
        _location(wrong_crop_suspected=True), "02/25/2026", "DATE"
    )
    assert assessment.detected
    assert assessment.signal_scores["upstream"] == 1


def test_unvalidated_contract_is_risk_not_acceptance_evidence():
    assessment = WrongCropDetector().assess(
        _location(stage=LocalizationStage.REGION_GEOMETRY_VALIDATED,
                  region_source="ANCHOR_RELATIVE_CONTRACT"), "224", "TYPE_OF_BILL"
    )
    assert assessment.detected
    assert assessment.risk == pytest.approx(.62)


def test_independent_and_correlated_agreement_remain_distinct():
    base = {
        "page_sha256": "page", "source_representation_id": "representation-a",
        "crop_sha256": "crop-a", "localization_id": "location-a",
        "preprocessing_profile": "profile-a", "preprocessing_sha256": "prep-a",
        "engine_family": "RAPIDOCR_FAMILY",
    }
    left = EvidenceProvenance(**base)
    correlated = EvidenceProvenance(**{**base, "engine_family": "PADDLEOCR_FAMILY"})
    independent = EvidenceProvenance(
        page_sha256="page", source_representation_id="representation-b",
        crop_sha256="crop-b", localization_id="location-b",
        preprocessing_profile="profile-b", preprocessing_sha256="prep-b",
        engine_family="TESSERACT_FAMILY",
    )
    service = EvidenceDependencyService()
    assert service.classify(left, correlated).relation is DependencyRelation.CORRELATED
    assert service.classify(left, independent).relation is DependencyRelation.INDEPENDENT


def test_field_specific_preprocessing_routes_are_versioned():
    registry = PreprocessingRegistry.load("config/ocr_preprocessing_phase8_10.yaml")
    assert registry.resolve("provider_npi", "npi") == "DIGIT_PRESERVING_V2"
    assert registry.resolve("patient_name", "text") == "NAME_STROKE_V2"
    assert registry.resolve("patient_dob", "date") == "DATE_DELIMITER_V2"
    assert registry.resolve("total_charge", "currency") == "CURRENCY_DECIMAL_V2"
    assert registry.config["version"] == "2.0-phase8.10-evaluation"


class _Provider:
    provider_name = "fake-local"
    provider_version = "1"
    calls = 0

    async def extract(self, request):
        self.calls += 1
        candidate = OCRCandidate(
            value="123", raw_value="123", engine="fake-local", model_name="fake",
            model_version="1", preprocessing_variant="DIGIT_PRESERVING_V2",
            raw_confidence=.9, calibrated_confidence=None,
            bounding_box=request.bounding_box, latency_ms=2,
        )
        return OCRResult((candidate,), "fake-local", "1", 2)


@pytest.mark.asyncio
async def test_cache_hit_preserves_provenance_and_avoids_second_execution():
    provider = _Provider()
    service = OCRExecutionService()
    request = OCRRequest(
        document_id="doc", page_number=1, field_name="member_id", field_type="code",
        form_type=ClaimFormType.CMS1500, image=Image.new("RGB", (20, 10), "white"),
        bounding_box=BoundingBox(x0=0, y0=0, x1=20, y1=10,
                                 image_width=20, image_height=10),
        page_sha256="page", preprocessing_profile="DIGIT_PRESERVING_V2",
        localization_evidence=_location(),
    )
    first = await service.execute(provider, request)
    second = await service.execute(provider, request)
    assert provider.calls == 1
    assert not first.cache_hit and second.cache_hit
    assert second.candidates[0].provenance == first.candidates[0].provenance
    assert second.execution_cache_key == first.execution_cache_key


def test_deterministic_npi_validator_is_not_weakened():
    assert not decide_local_candidate("1234567890", "NPI").accepted


def test_missing_promotion_artifact_rejects_instead_of_skipping(tmp_path, monkeypatch):
    monkeypatch.setattr(phase810, "BASELINE", tmp_path / "missing-baseline")
    monkeypatch.setattr(phase810, "OBSERVATIONS", tmp_path / "missing-observations")
    result = phase810.run(tmp_path / "output")
    assert result["decision"] == "REJECT"
    assert result["reason"] == "PROMOTION_NOT_EVALUABLE"
