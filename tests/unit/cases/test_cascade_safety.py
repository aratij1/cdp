from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType, FieldCriticality
from packages.ocr.contracts import OCRCandidate, OCRRequest
from workers.cascade.handwriting_detection import OpenCVHandwritingDetector, WritingType
from workers.cascade.reconciliation import (
    CandidateReconciler,
    FieldDisposition,
    claim_can_finalize,
)
from workers.page_detection.text_extraction import TextLine
from workers.retry.alternate_preprocessing import remove_printed_lines
from workers.standard_form_extraction.structured_fields import (
    parse_person_name,
    reconstruct_reading_order,
)


def _box():
    return BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100)


def _candidate(value: str, engine: str, confidence: float = 0.99):
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="1",
        preprocessing_variant="original",
        raw_confidence=confidence,
        calibrated_confidence=confidence,
        bounding_box=_box(),
        latency_ms=1,
    )


def test_high_confidence_invalid_candidate_is_never_accepted():
    result = CandidateReconciler(lambda value: value == "VALID").reconcile(
        [_candidate("WRONG", "paddle")], FieldCriticality.CRITICAL
    )
    assert result.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert result.selected is None


def test_critical_field_requires_independent_agreement():
    reconciler = CandidateReconciler(lambda value: True)
    one = reconciler.reconcile([_candidate("123", "paddle")], FieldCriticality.CRITICAL)
    two = reconciler.reconcile(
        [_candidate("123", "paddle"), _candidate("123", "tesseract")],
        FieldCriticality.CRITICAL,
    )
    assert one.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert two.disposition == FieldDisposition.VALIDATED_AUTOMATICALLY


def test_two_paddle_model_names_do_not_count_as_independent_engines():
    result = CandidateReconciler(lambda value: True).reconcile(
        [_candidate("123", "paddleocr"), _candidate("123", "pp-ocr-v5")],
        FieldCriticality.CRITICAL,
    )
    assert result.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED


def test_live_cascade_npi_requires_checksum_with_independent_ocr() -> None:
    reconciler = CandidateReconciler(lambda value: True)
    candidates = [_candidate("1234567893", "rapidocr"), _candidate("1234567893", "tesseract")]
    without_checksum = reconciler.reconcile(
        candidates, FieldCriticality.CRITICAL, "npi", document_family="CMS1500"
    )
    assert without_checksum.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert without_checksum.reasons == ("field_evidence_policy_not_satisfied",)
    with_checksum = reconciler.reconcile(
        candidates,
        FieldCriticality.CRITICAL,
        "npi",
        deterministic_evidence={"CHECKSUM_VALID"},
        document_family="CMS1500",
    )
    assert with_checksum.disposition == FieldDisposition.VALIDATED_AUTOMATICALLY


def test_unresolved_critical_field_blocks_claim_finalization():
    assert not claim_can_finalize({}, {"npi"})
    assert claim_can_finalize({"npi": FieldDisposition.VERIFIED_BY_HUMAN}, {"npi"})


def test_blank_detection_and_line_removal_safety():
    assert (
        OpenCVHandwritingDetector().classify(Image.new("L", (100, 30), 255)).writing_type
        == WritingType.BLANK
    )
    original = Image.new("L", (100, 30), 255)
    cleaned, accepted, loss = remove_printed_lines(original)
    assert cleaned.size == original.size
    assert accepted
    assert loss == 0


def test_name_semantics_and_address_reading_order():
    name = parse_person_name("DOE, JANE Q JR", "AUTO")
    assert (name.last, name.first, name.middle, name.suffix) == ("DOE", "JANE", "Q", "JR")
    tokens = [
        TextLine("SPRINGFIELD", 0, 20, 50, 30, 0.9),
        TextLine("MAIN", 30, 0, 60, 10, 0.9),
        TextLine("12", 0, 0, 10, 10, 0.9),
        TextLine("IL", 60, 20, 70, 30, 0.9),
    ]
    assert reconstruct_reading_order(tokens) == "12 MAIN\nSPRINGFIELD IL"


def test_common_ocr_request_keeps_field_context():
    request = OCRRequest(
        document_id="d",
        page_number=1,
        field_name="npi",
        field_type="npi",
        form_type=ClaimFormType.CMS1500,
        image=Image.new("L", (10, 10)),
        bounding_box=_box(),
        allowed_characters="0123456789",
        criticality=FieldCriticality.CRITICAL,
    )
    assert request.field_name == "npi"
