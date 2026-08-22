from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType, FieldCriticality
from packages.ocr.contracts import OCRCandidate, OCRRequest
from workers.cascade.field_pipeline import FieldCascade
from workers.cascade.handwriting_detection import HandwritingDetection, WritingType
from workers.cascade.reconciliation import CandidateReconciler, FieldDisposition


class Detector:
    def __init__(self, writing_type):
        self.writing_type = writing_type
    def classify(self, crop):
        return HandwritingDetection(self.writing_type, 0.9)


class Engine:
    def __init__(self, name, value):
        self.engine_name = self.model_name = name
        self.model_version = "1"
        self.value = value
        self.calls = 0
    def recognize(self, request):
        self.calls += 1
        return [OCRCandidate(
            value=self.value, raw_value=self.value, engine=self.engine_name,
            model_name=self.model_name, model_version="1",
            preprocessing_variant="original", raw_confidence=.99,
            calibrated_confidence=.99, bounding_box=request.bounding_box, latency_ms=1,
        )]


def _request():
    return OCRRequest(
        "d", 1, "npi", "npi", ClaimFormType.CMS1500, Image.new("L", (30, 10), 255),
        BoundingBox(x0=0, y0=0, x1=30, y1=10, image_width=30, image_height=10),
        criticality=FieldCriticality.CRITICAL,
    )


def test_mixed_npi_crop_runs_all_engines_but_still_requires_checksum_evidence():
    primary, secondary, handwriting = Engine("paddle", "123"), Engine("tesseract", "123"), Engine("trocr", "123")
    cascade = FieldCascade(
        primary, lambda field_type: secondary, handwriting, Detector(WritingType.MIXED),
        lambda request: CandidateReconciler(lambda value: value == "123"),
    )
    result = cascade.run(_request())
    assert {candidate.engine for candidate in result.candidates} == {"paddle", "tesseract", "trocr"}
    assert result.reconciliation.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert result.reconciliation.reasons == ("field_evidence_policy_not_satisfied",)


def test_blank_critical_field_routes_to_review_without_ocr():
    primary = Engine("paddle", "anything")
    cascade = FieldCascade(
        primary, lambda field_type: Engine("tesseract", "anything"), None,
        Detector(WritingType.BLANK),
        lambda request: CandidateReconciler(lambda value: True),
    )
    result = cascade.run(_request())
    assert result.reconciliation.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert primary.calls == 0
