from uuid import uuid4

import pytest
from PIL import Image

from packages.document_taxonomy.taxonomy import DocumentClass
from packages.domain.enums import ClaimFormType
from packages.domain.registration import RegistrationEvidence
from packages.extraction_geometry import (
    ExtractionGeometryDecision,
    ExtractionGeometryMode,
    FormIdentityDecision,
    FormIdentityStatus,
)
from packages.roi_resolution import (
    AnchorRelativeContract,
    ObservedAnchor,
    ROIResolutionMode,
    ROIResolutionRequest,
    ROIResolver,
)
from packages.standard_form_verification.contracts import (
    StandardFormStatus,
    StandardFormVerification,
)
from packages.templates.registry import (
    DEFAULT_TEMPLATE_DIR,
    TemplateNotFoundError,
    TemplateRegistry,
)
from packages.templates.selection import (
    exact_family_template,
    form_type_from_template_lineage,
)
from workers.page_detection.template_alignment import align_to_reference
from workers.page_detection.template_compatibility import (
    TemplateCompatibilityEvidence,
    TemplateCompatibilityStatus,
)
from workers.retry.consumer import RetryWorker
from workers.standard_form_extraction.extractor import StandardFormExtractionService


def _identity(family=DocumentClass.CMS1500):
    return FormIdentityDecision(
        family=family, status=FormIdentityStatus.VERIFIED, score=.99
    )


def _compatibility(status=TemplateCompatibilityStatus.COMPATIBLE):
    return TemplateCompatibilityEvidence(
        family="CMS1500", family_compatibility=1, aspect_ratio_similarity=1,
        line_structure_similarity=1, edge_projection_similarity=1,
        anchor_visibility=1, normalized_layout_similarity=1,
        form_fingerprint_similarity=1, compatibility_score=.99, status=status,
    )


def _registration(**updates):
    values = {
        "algorithm": "test", "accepted": True, "corner_validity": True,
        "transform_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "alignment_confidence": .99,
    }
    values.update(updates)
    return RegistrationEvidence(**values)


def _fixed_geometry(**updates):
    values = {
        "mode": ExtractionGeometryMode.REGISTERED_FIXED,
        "form_identity": _identity(), "template_id": "cms1500",
        "template_version": "02-12", "compatibility": _compatibility(),
        "registration": _registration(), "transformed_geometry_valid": True,
    }
    values.update(updates)
    return ExtractionGeometryDecision(**values)


@pytest.mark.parametrize("updates", [
    {"registration": None},
    {"registration": _registration(accepted=False)},
    {"compatibility": _compatibility(TemplateCompatibilityStatus.INCOMPATIBLE)},
    {"transformed_geometry_valid": False},
    {"registration": _registration(corner_validity=False)},
])
def test_fixed_geometry_fails_closed_without_all_authorities(updates):
    with pytest.raises(ValueError):
        _fixed_geometry(**updates)


def test_verified_identity_is_preserved_when_geometry_requires_layout_fallback():
    verification = StandardFormVerification(
        candidate_family=DocumentClass.CMS1500,
        status=StandardFormStatus.VERIFIED,
        verification_score=.98,
        eligible_for_fixed_extractor=False,
    )
    identity = FormIdentityDecision.from_standard_verification(verification)
    geometry = ExtractionGeometryDecision(
        mode=ExtractionGeometryMode.STRUCTURAL_LAYOUT,
        form_identity=identity,
        reason_codes=("REGISTRATION_NOT_ACCEPTED",),
    )
    assert identity.status == FormIdentityStatus.VERIFIED
    assert geometry.mode == ExtractionGeometryMode.STRUCTURAL_LAYOUT
    assert not geometry.authorizes_fixed_roi


def test_roi_resolver_requires_registered_fixed_authority():
    resolver = ROIResolver()
    resolved = resolver.resolve(ROIResolutionRequest(
        field_name="patient_name", page_width=1000, page_height=1200,
        geometry=_fixed_geometry(), fixed_region=(10, 20, 200, 80),
    ))
    assert resolved.mode == ROIResolutionMode.FIXED_REGISTERED
    fallback = ExtractionGeometryDecision(
        mode=ExtractionGeometryMode.STRUCTURAL_LAYOUT, form_identity=_identity()
    )
    unresolved = resolver.resolve(ROIResolutionRequest(
        field_name="patient_name", page_width=1000, page_height=1200,
        geometry=fallback, fixed_region=(10, 20, 200, 80),
    ))
    assert unresolved.mode == ROIResolutionMode.UNRESOLVED


def test_anchor_relative_roi_uses_field_specific_contract_not_form_identity_coordinates():
    geometry = ExtractionGeometryDecision(
        mode=ExtractionGeometryMode.ANCHOR_RELATIVE, form_identity=_identity()
    )
    result = ROIResolver().resolve(ROIResolutionRequest(
        field_name="patient_name", page_width=1000, page_height=1200,
        geometry=geometry,
        anchor_contract=AnchorRelativeContract(
            field_name="patient_name", anchor_id="PATIENT_NAME_LABEL",
            x0_offset=.02, y0_offset=0, x1_offset=.25, y1_offset=.04,
        ),
        observed_anchors=(ObservedAnchor(
            anchor_id="PATIENT_NAME_LABEL", bbox=(100, 200, 180, 220), confidence=.95
        ),),
    ))
    assert result.mode == ROIResolutionMode.ANCHOR_RELATIVE
    assert result.bbox == (120, 200, 350, 248)


def test_template_selection_never_crosses_form_family():
    registry = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    assert exact_family_template(registry, ClaimFormType.UB04).form_type == ClaimFormType.UB04
    with pytest.raises(ValueError):
        form_type_from_template_lineage("custom-form@v1")
    ub_only = TemplateRegistry([exact_family_template(registry, ClaimFormType.UB04)])
    with pytest.raises(TemplateNotFoundError):
        exact_family_template(ub_only, ClaimFormType.CMS1500)


def test_incompatible_template_precheck_never_attempts_sift(monkeypatch):
    candidate = Image.new("L", (1000, 300), 255)
    reference = Image.new("L", (500, 1000), 255)
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("SIFT must not run for incompatible template lineage")

    monkeypatch.setattr("workers.page_detection.template_alignment._sift_alignment", forbidden)
    result = align_to_reference(
        candidate, reference, family="CMS1500", enforce_compatibility_precheck=True
    )
    assert not result.success
    assert not result.sift_attempted
    assert not called


class _CountingExtractor:
    engine_name = "rapidocr"

    def __init__(self):
        self.region_calls = 0

    def extract(self, image):
        return []

    def extract_region(self, image, x0, y0, x1, y1):
        self.region_calls += 1
        return []


def test_ub04_service_line_engine_uses_one_table_ocr_call():
    template = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR).latest_for_form_type(
        ClaimFormType.UB04
    )
    extractor = _CountingExtractor()
    service = StandardFormExtractionService(extractor)
    _, result = service.extract_ub04_service_lines(
        Image.new("L", (
            template.reference_dimensions.width_px,
            template.reference_dimensions.height_px,
        ), 255),
        template, 1, registration_confidence=1.0,
    )
    assert result is not None
    assert extractor.region_calls == 1


def test_runtime_and_evaluation_roi_resolution_are_identical():
    request = ROIResolutionRequest(
        field_name="patient_name", page_width=1000, page_height=1200,
        geometry=_fixed_geometry(), fixed_region=(10, 20, 200, 80),
    )
    assert ROIResolver().resolve(request) == ROIResolver().resolve(request)


def test_retry_engine_initialization_is_reused_per_worker():
    worker = RetryWorker.__new__(RetryWorker)
    worker._engine_cache = {}
    created = []

    def factory():
        created.append(uuid4())
        return object()

    first = worker._engine("rapidocr", factory)
    second = worker._engine("rapidocr", factory)
    assert first is second
    assert len(created) == 1
