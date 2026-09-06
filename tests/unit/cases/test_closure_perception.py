"""Known-source geometry and truth-scope regressions; no real patient fixtures."""

from dataclasses import replace

import pytest
from PIL import Image

from evaluation.closure_bottlenecks import decompose
from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRRequest
from packages.ocr.preprocessing import PreprocessingRegistry
from packages.ocr.rapidocr_provider import RapidOCRProvider


def row(**kwargs):
    base = {
        "claim_id": "synthetic",
        "field": "member_id",
        "authority": "FROZEN_REGRESSION",
        "truth": "EXAMPLE123",
        "candidates": ["EXAMPLE123"],
        "top1": "EXAMPLE123",
        "accepted": False,
    }
    return base | kwargs


@pytest.mark.parametrize(
    "authority",
    [
        "FROZEN_REGRESSION",
        "SYNTHETIC_KNOWN_SOURCE",
        "UNLABELED",
        "WEAK_LLM_CONSENSUS",
        "ARITHMETIC_EXACT",
    ],
)
def test_engineering_references_never_qualify_release(authority):
    result = decompose(
        [row(authority=authority, source_binding_verified=True, truth_sha256="hash")],
        scope="RELEASE",
    )
    assert result["summary"]["evaluated_fields"] == 0
    assert result["summary"]["recall"]["R@5"] is None


def test_release_reference_requires_source_binding():
    assert (
        decompose([row(authority="TRUSTED_HUMAN")], scope="RELEASE")["summary"]["evaluated_fields"]
        == 0
    )
    result = decompose(
        [row(authority="TRUSTED_HUMAN", source_binding_verified=True, truth_sha256="frozen")],
        scope="RELEASE",
    )
    assert result["summary"]["evaluated_fields"] == 1


@pytest.mark.parametrize(
    "changes,bucket",
    [
        ({"candidates": ["WRONG"], "top1": "WRONG"}, "TRUTH_NOT_IN_CANDIDATES"),
        (
            {"candidates": ["WRONG", "EXAMPLE123"], "top1": "WRONG"},
            "TRUTH_IN_CANDIDATES_WRONG_RANK",
        ),
        ({}, "TRUTH_TOP1_BUT_REJECTED"),
        ({"authority_blocked": True}, "TRUTH_TOP1_AUTHORITY_BLOCKED"),
        ({"external_evidence_blocked": True}, "TRUTH_TOP1_EXTERNAL_EVIDENCE_BLOCKED"),
        ({"reference_conflict": True}, "REFERENCE_CONFLICT"),
        ({"authority": "UNLABELED"}, "NOT_EVALUABLE"),
        ({"accepted": True}, "CORRECT_ACCEPTED"),
    ],
)
def test_bottleneck_routing(changes, bucket):
    result = decompose([row(**changes)], scope="ENGINEERING")
    assert result["fields"][0]["bucket"] == bucket
    assert "EXAMPLE123" not in str(result)


def test_recall_denominator_conflicts_and_candidate_inflation():
    rows = [
        row(candidates=["WRONG", "EXAMPLE123"], top1="WRONG"),
        row(claim_id="missing", candidates=[]),
        row(claim_id="unknown", authority="UNLABELED"),
        row(claim_id="conflict", reference_conflict=True),
    ]
    summary = decompose(rows, scope="ENGINEERING")["summary"]
    assert summary["evaluated_fields"] == 2
    assert summary["recall"] == {"R@1": 0, "R@3": 0.5, "R@5": 0.5}
    with pytest.raises(ValueError, match="DUPLICATE"):
        decompose([row(), row()], scope="ENGINEERING")


def registry(steps):
    return PreprocessingRegistry(
        {"profiles": {"TEST": steps}, "default_profile": "TEST", "version": "test"}
    )


@pytest.mark.parametrize(
    "steps,prepared_box",
    [
        ([], (10, 5, 60, 20)),
        (["safe_border"], (14, 9, 64, 24)),
        (["upscale_2x"], (20, 10, 120, 40)),
        (["safe_border", "upscale_2x"], (28, 18, 128, 48)),
        (["upscale_2x", "safe_border"], (27, 17, 127, 47)),
    ],
)
def test_preprocessing_inverse_matches_known_source_pixels(steps, prepared_box):
    prepared = registry(steps).apply(Image.new("L", (100, 30)), "test", "test")
    assert prepared.source_box(*prepared_box) == pytest.approx((10, 5, 60, 20))


def test_rotation_and_border_inverse_preserve_original_axes():
    prepared = registry(["orient_field_crop", "safe_border", "upscale_2x"]).apply(
        Image.new("L", (30, 100)), "test", "test"
    )
    assert prepared.source_box(28, 28, 128, 58) == pytest.approx((5, 10, 20, 60))


def test_rapidocr_page_geometry_removes_border_instead_of_rescaling_it():
    image = Image.new("RGB", (100, 30))
    box = BoundingBox(x0=200, y0=300, x1=300, y1=330, image_width=1000, image_height=1000)
    request = OCRRequest("synthetic", 1, "member_id", "id", ClaimFormType.CMS1500, image, box)
    backend = lambda _: ([[[[14, 9], [64, 9], [64, 24], [14, 24]], "EXAMPLE123", 0.99]], [])
    provider = RapidOCRProvider(backend=backend, preprocessing=registry(["safe_border"]))
    result = provider._extract_sync(request)
    token = result.candidates[0].tokens[0]
    assert token.bounding_box.normalized() == pytest.approx((0.21, 0.305, 0.26, 0.32))
    assert token.text == "EXAMPLE123"
    assert result.candidates[0].provenance is not None
    # Entirely padded detections are not mapped into plausible source observations.
    provider._backend = lambda _: ([[[[0, 0], [2, 0], [2, 2], [0, 2]], "EDGE", 0.99]], [])
    assert not provider._extract_sync(replace(request, field_name="test")).candidates[0].tokens


@pytest.mark.parametrize(
    "field,value,page",
    list(
        __import__(
            "evaluation.closure_candidate_probe", fromlist=["known_source_pages"]
        ).known_source_pages()
    ),
)
def test_numbered_labels_scale_and_translation_recover_known_fields(field, value, page):
    from packages.claim_intelligence.provenance import independent
    from packages.claim_intelligence.spatial import SpatialCandidateExtractor

    result = SpatialCandidateExtractor().extract(page)
    assert [c.value for c in result[field]] == [value]
    assert len(result[field]) <= 5
    for a in result[field][0].evidence:
        assert not independent(a, a)
    assert not SpatialCandidateExtractor().extract(replace(page, form_type="OTHER_CLAIM_FORM"))
    assert not SpatialCandidateExtractor().extract(replace(page, form_type="UNKNOWN"))


def test_label_normalization_never_discards_unrecognized_suffix_or_value():
    from packages.claim_intelligence.spatial import label_key

    assert label_key("2. PATIENT'S NAME (Last, First, Middle)") == "PATIENTSNAME"
    assert label_key("PATIENT NAME EXAMPLE PERSON") == "PATIENTNAMEEXAMPLEPERSON"
    assert label_key("12345 PATIENT NAME") == "12345PATIENTNAME"


def test_invalid_dates_stay_in_source_tokens_but_not_field_candidates():
    from evaluation.closure_candidate_probe import known_source_pages
    from packages.claim_intelligence.spatial import SpatialCandidateExtractor

    _, _, page = next(x for x in known_source_pages() if x[0] == "patient_dob")
    invalid = replace(page.tokens[1], text="MM DD YY", normalized_text="MM DD YY")
    changed = replace(page, tokens=(page.tokens[0], invalid))
    assert "patient_dob" not in SpatialCandidateExtractor().extract(changed)
    assert invalid in changed.tokens


def test_repeated_alternatives_bounded_without_fake_independence():
    from packages.claim_intelligence.models import Candidate, CandidateEvidence
    from packages.claim_intelligence.spatial import bounded_candidates

    evidence = CandidateEvidence("OCR", 0.99, "page", "crop", "region")
    values = [Candidate(str(i), "VALUE" + str(i // 2), (evidence,)) for i in range(20)]
    result = bounded_candidates(values)
    assert len(result) == 5
    assert len({c.value for c in result}) == 5
    assert all(c.evidence == (evidence,) for c in result)


@pytest.mark.asyncio
async def test_execution_cache_separates_source_regions_and_preprocessing():
    from packages.ocr.execution import OCRExecutionService

    calls = []

    def backend(_):
        calls.append(1)
        return ([[[[14, 9], [64, 9], [64, 24], [14, 24]], "EXAMPLE123", 0.99]], [])

    provider = RapidOCRProvider(backend=backend, preprocessing=registry(["safe_border"]))
    image = Image.new("RGB", (100, 30))
    box = BoundingBox(x0=100, y0=100, x1=200, y1=130, image_width=1000, image_height=1000)
    request = OCRRequest(
        "synthetic",
        1,
        "member_id",
        "id",
        ClaimFormType.CMS1500,
        image,
        box,
        document_sha256="source",
        page_sha256="page",
    )
    service = OCRExecutionService(benchmark_mode=False)
    first = await service.execute(provider, request)
    repeated = await service.execute(provider, request)
    assert repeated.cache_hit and len(calls) == 1
    assert repeated.candidates == first.candidates
    moved = replace(request, bounding_box=box.model_copy(update={"x0": 200, "x1": 300}))
    separate = await service.execute(provider, moved)
    assert not separate.cache_hit and len(calls) == 2
    assert separate.candidates[0].provenance.bbox != first.candidates[0].provenance.bbox
    provider.preprocessing = registry([])
    changed = await service.execute(provider, request)
    assert not changed.cache_hit and len(calls) == 3


@pytest.mark.parametrize(
    "value,valid",
    [
        ("01 02 1980", True),
        ("01.02.1980", True),
        ("01 02 80", False),
        ("O1.02.1980", False),
        ("02.30.1980", False),
    ],
)
def test_date_cell_punctuation_and_complete_year(value, valid):
    from packages.claim_intelligence.normalization import normalize

    assert normalize("patient_dob", value)[1] is valid


def test_neighbor_charge_not_selected_and_small_box_overlap_allowed():
    from packages.claim_intelligence.document import DocumentPage, Token
    from packages.claim_intelligence.spatial import SpatialCandidateExtractor

    def token(text, box):
        return Token(text, text, box, 0.99, "test", "page", str(box), "inv", "source", "crop")

    tokens = (
        token("28. TOTAL CHARGE", (100, 100, 200, 120)),
        token("29. AMOUNT PAID", (240, 100, 330, 120)),
        token("123.45", (110, 118, 180, 140)),
        token("99.00", (245, 125, 315, 145)),
    )
    page = DocumentPage("page", "package", "CMS1500", "VERIFIED", 1000, 1000, "UNKNOWN", tokens)
    result = SpatialCandidateExtractor().extract(page)
    assert [c.value for c in result["total_charge"]] == ["123.45"]


def test_date_assembly_excludes_sex_flags():
    from packages.claim_intelligence.document import DocumentPage, Token
    from packages.claim_intelligence.spatial import SpatialCandidateExtractor

    def token(text, box):
        return Token(text, text, box, 0.99, "test", "page", str(box), "inv", "source", "crop")

    tokens = (
        token("3. PATIENTS BIRTH DATE", (100, 100, 250, 120)),
        token("01.02.1980", (110, 118, 190, 140)),
        token("M", (200, 120, 210, 140)),
    )
    page = DocumentPage("page", "package", "CMS1500", "VERIFIED", 1000, 1000, "UNKNOWN", tokens)
    result = SpatialCandidateExtractor().extract(page)
    assert result["patient_dob"][0].normalized_value == "1980-01-02"


def test_performance_gate_requires_identical_semantics_and_cohort():
    from evaluation.closure_performance_gate import compare_runs

    p = {
        "page_id": "same",
        "token_evidence_sha256": "token",
        "candidate_semantics_sha256": "candidate",
        "strict_family": "CMS1500",
        "identity_confirmed": True,
        "canonical_localization_invoked": False,
    }
    base = {"pages": [p], "latency": {"P95": 20}}
    fast = {"pages": [p], "latency": {"P95": 10}}
    assert compare_runs(base, fast)["status"] == "ENGINEERING_EVIDENCE_PASS"
    changed = {"pages": [p | {"candidate_semantics_sha256": "changed"}], "latency": {"P95": 10}}
    assert compare_runs(base, changed)["status"] == "ENGINEERING_EVIDENCE_FAIL"
    with pytest.raises(ValueError, match="COHORT"):
        compare_runs(base, {"pages": [], "latency": {"P95": 0}})
