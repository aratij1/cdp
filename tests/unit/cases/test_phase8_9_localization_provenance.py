from __future__ import annotations

from PIL import Image

from evaluation import phase8_9_localization_provenance as phase89
from packages.criticality import CriticalityLevel
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.evidence import StructuralLocalizationEvidence, StructuralLocalizationType
from packages.evidence_decision import DecisionContext, EvidenceDecisionService
from packages.evidence_dependency import DependencyRelation, EvidenceDependencyService
from packages.extraction_geometry import (
    ExtractionGeometryDecision,
    ExtractionGeometryMode,
    FormIdentityDecision,
    FormIdentityStatus,
)
from packages.field_localization import (
    DynamicROIResolver,
    FieldDefinition,
    FieldLocator,
    FieldRelationship,
    LocalizationMetricRecord,
    PageZone,
    RegionOutcome,
    aggregate_localization,
    classify_region,
)
from packages.ocr import OCRExecutionService, OCRRequest, RapidOCRProvider
from packages.ocr.contracts import OCRCandidate
from packages.ocr.provenance import EvidenceProvenance
from packages.page_observation import PageObservationService
from workers.page_detection.text_extraction import TextLine


class FixtureOCR:
    model_version = "fixture-v1"

    def __init__(self, lines):
        self.lines = lines

    def extract(self, _image):
        return self.lines


def _definition(field: str, datatype: str, relation: str = "below"):
    return FieldDefinition(
        field_name=field, form_family="CMS1500", aliases=(field.replace("_", " "),),
        page_zone=PageZone.ANY,
        relationships=(FieldRelationship(
            relation=relation, x0_offset=0, y0_offset=.01, x1_offset=.30, y1_offset=.08
        ),),
        datatype=datatype, blocking=True, criticality="CRITICAL",
        definition_version="phase8.9-test",
    )


def _observation(lines):
    return PageObservationService(
        FixtureOCR(lines), preprocessing_version="fixture-v1"
    ).observe("page-1", Image.new("RGB", (1000, 1200), "white"))


def _provenance(tag: str, *, shared: bool) -> EvidenceProvenance:
    suffix = "shared" if shared else tag
    box = BoundingBox(
        x0=100 if shared or tag == "rapid" else 500, y0=100,
        x1=250 if shared or tag == "rapid" else 650, y1=150,
        image_width=1000, image_height=1200,
    )
    return EvidenceProvenance(
        page_sha256="page", source_representation_id=f"representation-{suffix}",
        observation_id=f"observation-{suffix}", crop_sha256=f"crop-{suffix}",
        localization_id=f"location-{suffix}", localization_method="TOKEN_SPAN",
        localization_version="field-locator-v3-multi-candidate",
        preprocessing_profile=f"profile-{suffix}",
        preprocessing_sha256=f"preprocessing-{suffix}",
        engine_family=f"{tag}_family", engine_name=tag, engine_version="1",
        model_family=f"{tag}_model", model_name=tag, model_version="1",
        invocation_id=f"invocation-{tag}", source_candidate_id=f"candidate-{tag}", bbox=box,
    )


def _candidate(tag: str, value: str, *, shared: bool) -> OCRCandidate:
    provenance = _provenance(tag, shared=shared)
    return OCRCandidate(
        value=value, raw_value=value, engine=tag, model_name=tag, model_version="1",
        preprocessing_variant=provenance.preprocessing_profile or "unknown",
        raw_confidence=.99, calibrated_confidence=None,
        bounding_box=provenance.bbox, latency_ms=1, provenance=provenance,
    )


def _structure(field: str) -> StructuralLocalizationEvidence:
    return StructuralLocalizationEvidence(
        evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
        confidence=.99, confirmed=True,
        reason_codes=("BOUNDED_ALIAS_MATCH", "OBSERVED_VALUE_SPAN_GEOMETRY"),
        source="test", field_name=field, field_bbox=(100, 100, 250, 150),
        localization_mode="ANCHOR_RELATIVE", positive_bounded_roi=True, geometry_valid=True,
    )


def test_correct_anchor_with_competing_valid_date_is_flagged_and_not_resolved():
    observation = _observation([
        TextLine("PATIENT DOB", 100, 100, 260, 125, .99),
        TextLine("01/02/1980", 100, 145, 230, 170, .98),
        TextLine("03/04/1981", 245, 145, 375, 170, .98),
    ])
    location = FieldLocator().locate(observation, _definition("patient_dob", "DATE"))
    assert location.anchor_text == "patient dob"
    assert len(location.candidates) >= 2
    assert location.wrong_crop_suspected
    assert "WRONG_CROP_NEIGHBOR_FIELD" in location.reason_codes
    geometry = ExtractionGeometryDecision(
        mode=ExtractionGeometryMode.ANCHOR_RELATIVE,
        form_identity=FormIdentityDecision(
            family=DocumentClass.CMS1500, status=FormIdentityStatus.VERIFIED, score=1
        ),
    )
    resolved = DynamicROIResolver().resolve(
        "patient_dob", anchor=location, structural=None, geometry=geometry
    )
    assert resolved.mode.value == "UNRESOLVED"
    assert "WRONG_CROP_CANDIDATE_REJECTED" in resolved.reason_codes


def test_two_engines_agreeing_on_wrong_crop_cannot_auto_accept():
    decision = EvidenceDecisionService().decide(DecisionContext(
        field_name="patient_dob", document_family="CMS1500", criticality=CriticalityLevel.C2,
        candidates=[_candidate("rapid", "01/02/1980", shared=True),
                    _candidate("paddle", "01/02/1980", shared=True)],
        deterministic_evidence={"FORMAT_VALID", "DATE_VALID"},
        hard_validation_passed=True, structural_localization=_structure("patient_dob"),
        wrong_crop_suspected=True,
    ))
    assert decision.disposition.value not in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}


def test_dependency_graph_classifies_shared_and_distinct_lineage():
    service = EvidenceDependencyService()
    correlated = service.classify(_provenance("rapid", shared=True),
                                  _provenance("paddle", shared=True))
    distinct = service.classify(_provenance("rapid", shared=False),
                                _provenance("paddle", shared=False))
    assert correlated.relation is DependencyRelation.CORRELATED
    assert distinct.relation is DependencyRelation.INDEPENDENT


def test_checksum_invalid_npi_false_agreement_is_blocked():
    decision = EvidenceDecisionService().decide(DecisionContext(
        field_name="provider_npi", document_family="CMS1500", criticality=CriticalityLevel.C2,
        candidates=[_candidate("rapid", "1234567890", shared=False),
                    _candidate("paddle", "1234567890", shared=False)],
        deterministic_evidence=set(), hard_validation_passed=False,
        structural_localization=_structure("provider_npi"),
    ))
    assert decision.disposition.value not in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED"}


def test_neighboring_patient_and_provider_names_create_structural_conflict():
    observation = _observation([
        TextLine("PATIENT NAME", 100, 100, 250, 125, .99),
        TextLine("JANE SMITH", 100, 145, 230, 170, .98),
        TextLine("JANE CLINIC", 245, 145, 390, 170, .98),
    ])
    location = FieldLocator().locate(observation, _definition("patient_name", "PERSON_NAME"))
    assert location.wrong_crop_suspected
    assert "MULTIPLE_COMPETING_FIELD_VALUES" in location.reason_codes


def test_template_registration_failure_remains_unresolved():
    geometry = ExtractionGeometryDecision(
        mode=ExtractionGeometryMode.ANCHOR_RELATIVE,
        form_identity=FormIdentityDecision(
            family=DocumentClass.CMS1500, status=FormIdentityStatus.VERIFIED, score=1
        ),
    )
    result = DynamicROIResolver().resolve(
        "member_id", anchor=None, structural=None, geometry=geometry,
        registered_template_bbox=(10, 10, 100, 40),
    )
    assert result.mode.value == "UNRESOLVED"


def test_localization_metrics_measure_containment_and_wrong_crop_detection():
    good = LocalizationMetricRecord(
        document_id="d1", document_family="CMS1500", field_name="member_id",
        source="A", critical=True, strategy="TOKEN_SPAN", predicted_bbox=(8, 8, 102, 32),
        expected_bbox=(10, 10, 100, 30), confidence=.9, wrong_crop_detected=False,
    )
    bad = LocalizationMetricRecord(
        document_id="d2", document_family="CMS1500", field_name="member_id",
        source="A", critical=True, strategy="TOKEN_SPAN", predicted_bbox=(300, 10, 400, 30),
        expected_bbox=(10, 10, 100, 30), confidence=.6, wrong_crop_detected=True,
    )
    assert classify_region(good) is RegionOutcome.GEOMETRIC_MATCH
    assert classify_region(bad) is RegionOutcome.WRONG_REGION
    metrics = aggregate_localization([good, bad])
    assert metrics["wrong_crop_recall"] == 1
    assert metrics["wrong_crop_precision"] == 1


async def test_governed_ocr_execution_completes_provenance():
    provider = RapidOCRProvider(backend=lambda _pixels: ([[None, "ABC123", .98]], 1.0))
    request = OCRRequest(
        document_id="document", page_number=1, field_name="member_id", field_type="code",
        form_type=ClaimFormType.CMS1500, image=Image.new("RGB", (100, 40), "white"),
        bounding_box=BoundingBox(x0=0, y0=0, x1=100, y1=40,
                                 image_width=100, image_height=40),
        document_sha256="document-hash", page_sha256="page-hash",
        source_representation_id="render-300dpi",
    )
    result = await OCRExecutionService().execute(provider, request)
    provenance = result.candidates[0].provenance
    assert provenance is not None
    assert provenance.invocation_id
    assert provenance.crop_sha256
    assert provenance.preprocessing_sha256
    assert provenance.engine_version


def test_missing_promotion_data_is_not_silently_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(phase89, "BASELINE", tmp_path / "missing")
    result = phase89.run(tmp_path / "output")
    assert result["decision"] == "PROMOTION_NOT_EVALUABLE"
    assert result["missing_artifacts"]
