from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence import (
    EvidenceClass, EvidenceGapRouter, EvidencePolicy, StructuralLocalizationEvidence,
    StructuralLocalizationType, build_evidence_bundle,
)
from packages.ocr.contracts import OCRCandidate
from packages.ocr.provenance import EvidenceProvenance


def _candidate(engine: str, value: str, variant: str = "original") -> OCRCandidate:
    box = BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=10, image_height=10)
    provenance_box = box if engine == "rapidocr" else BoundingBox(
        x0=5, y0=5, x1=6, y1=6, image_width=10, image_height=10
    )
    return OCRCandidate(
        value=value, raw_value=value, engine=engine, model_name=engine,
        model_version="1", preprocessing_variant=variant, raw_confidence=.95,
        calibrated_confidence=None,
        bounding_box=box,
        latency_ms=1,
        provenance=EvidenceProvenance(
            page_sha256="page", source_representation_id=f"rep-{engine}",
            observation_id=f"obs-{engine}", crop_sha256=f"crop-{engine}",
            localization_id=f"loc-{engine}", localization_method=f"method-{engine}",
            preprocessing_profile=variant, engine_family=engine, model_family=engine,
            bbox=provenance_box,
        ),
    )


def test_same_engine_preprocessing_does_not_create_e2():
    bundle = build_evidence_bundle(
        field_name="patient_dob",
        candidates=[_candidate("rapidocr", "01011990"), _candidate("rapidocr", "01011990", "clahe")],
        registration_confidence=.95, wrong_crop_suspected=False,
        deterministic_evidence=set(), hard_validation_passed=True,
    )
    assert EvidenceClass.E2 not in bundle.available_classes


def test_independent_engines_create_e2_and_policy_can_accept_e2_e4():
    bundle = build_evidence_bundle(
        field_name="patient_dob",
        candidates=[
            _candidate("rapidocr", "01011990"),
            _candidate("tesseract", "01011990", "expanded-binarized"),
        ],
        registration_confidence=.95, wrong_crop_suspected=False,
        deterministic_evidence={"DATE_RELATIONSHIP_VALID"}, hard_validation_passed=True,
        structural_localization=StructuralLocalizationEvidence(
            evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
            confidence=.99, confirmed=True, reason_codes=("FIELD_SPECIFIC",), source="test",
            field_name="patient_dob", field_bbox=(0, 0, 1, 1),
            localization_mode="ANCHOR_RELATIVE", positive_bounded_roi=True, geometry_valid=True,
        ),
    )
    satisfied, available, missing, reasons = EvidencePolicy.load().evaluate(
        "patient_dob", CriticalityLevel.C2, bundle
    )
    assert satisfied
    assert {"E2", "E4"} <= set(available)
    assert missing == reasons == ()


def test_gap_router_selects_cheap_deterministic_evidence_before_cloud():
    opportunity = EvidenceGapRouter().route(("E4", "E7"))
    assert opportunity.action == "DETERMINISTIC_VALIDATION"
