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
    assert not provider._extract_sync(replace(request, field_name="test")).candidates


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


@pytest.mark.parametrize(
    "field,value,page",
    list(
        __import__(
            "evaluation.closure_candidate_probe", fromlist=["known_source_pages"]
        ).known_source_pages()
    ),
)
def test_noncanonical_discovery_preserves_identity_and_authority(field, value, page):
    from packages.claim_intelligence.discovery import NoncanonicalDiscovery
    from packages.claim_intelligence.spatial import SpatialCandidateExtractor

    noncanonical = replace(page, form_type="OTHER_CLAIM_FORM", form_identity_state="NOT_VERIFIED")
    result = NoncanonicalDiscovery().extract(noncanonical)
    assert any(c.value == value for c in result.candidates[field])
    assert result.authority == "UNVERIFIED_DISCOVERY"
    assert not result.canonical_localization and not result.production_authority
    assert not SpatialCandidateExtractor().extract(noncanonical)
    assert not NoncanonicalDiscovery().extract(page).candidates
    assert (
        not NoncanonicalDiscovery().extract(replace(noncanonical, form_type="UNKNOWN")).candidates
    )


def test_discovery_repeats_never_manufacture_independent_evidence():
    from evaluation.closure_candidate_probe import known_source_pages
    from packages.claim_intelligence.discovery import NoncanonicalDiscovery
    from packages.claim_intelligence.provenance import independent

    _, _, page = next(known_source_pages())
    page = replace(page, form_type="OTHER_CLAIM_FORM", tokens=page.tokens + page.tokens)
    result = NoncanonicalDiscovery().extract(page)
    assert len(result.candidates.get("member_id", [])) <= 3
    for candidate in result.candidates.get("member_id", []):
        for a in candidate.evidence:
            for b in candidate.evidence:
                assert not independent(a, b)


def test_noncanonical_same_line_candidates_stop_at_neighbor_label():
    from packages.claim_intelligence.discovery import NoncanonicalDiscovery
    from packages.claim_intelligence.document import DocumentPage, Token

    def token(text, box):
        return Token(text, text, box, 0.99, "test", "page", str(box), "inv", "source", "crop")

    label = token("MEMBER ID", (100, 100, 210, 120))
    value = token("EXAMPLE123", (220, 100, 310, 120))
    page = DocumentPage(
        "page", "package", "OTHER_CLAIM_FORM", "NOT_VERIFIED", 1000, 1000, "UNKNOWN", (label, value)
    )
    assert NoncanonicalDiscovery().extract(page).candidates["member_id"][0].value == "EXAMPLE123"
    neighbor = token("NPI", (212, 100, 218, 120))
    assert (
        not NoncanonicalDiscovery()
        .extract(replace(page, tokens=(label, neighbor, value)))
        .candidates.get("member_id")
    )


def test_shadow_pipeline_returns_discovery_without_changing_claim_decisions():
    from evaluation.closure_candidate_probe import known_source_pages
    from packages.claim_intelligence.models import ClaimGraph, FieldNode
    from packages.claim_intelligence.pipeline import (
        CDP2ShadowPipeline,
        LegacyFieldResult,
        LegacyResult,
    )

    _, _, page = next(known_source_pages())
    page = replace(page, form_type="OTHER_CLAIM_FORM", form_identity_state="NOT_VERIFIED")
    legacy = LegacyResult(
        "claim",
        (
            LegacyFieldResult(
                "member_id", None, False, (), ("NO_CANDIDATE",), ("AUTHORITY_REQUIRED",), True
            ),
        ),
        "immutable",
        "OTHER_CLAIM_FORM",
        (page.page_id,),
    )
    graph = ClaimGraph(
        "claim",
        "OTHER_CLAIM_FORM",
        {"member_id": FieldNode("member_id")},
        page_ids=(page.page_id,),
        package_id=page.package_id,
    )
    comparison = CDP2ShadowPipeline().compare(legacy, graph, (page,))
    assert comparison.legacy is legacy
    assert comparison.discovery_candidates[0].candidates["member_id"]
    assert comparison.cdp2.fields[0].proposed_value is None
    assert not comparison.runtime_authority and not comparison.cdp2.production_authority
    assert (
        comparison.legacy_metrics["technical_blockers"]
        == comparison.cdp2_metrics["technical_blockers"]
    )


def test_cpu_arena_rebuild_preserves_models_and_options_atomically(monkeypatch):
    import sys
    from types import SimpleNamespace

    from packages.ocr.runtime import enable_cpu_arena

    constructed = []

    class Session:
        def __init__(self, name):
            self._model_path = name

        def get_providers(self):
            return ["CPUExecutionProvider"]

        def get_provider_options(self):
            return {"CPUExecutionProvider": {"arena_extend_strategy": "kSameAsRequested"}}

        def get_session_options(self):
            return SimpleNamespace(enable_cpu_mem_arena=False, intra_op_num_threads=8)

    wrappers = [SimpleNamespace(session=Session(name)) for name in ("det", "cls", "rec")]
    backend = SimpleNamespace(
        text_det=SimpleNamespace(infer=wrappers[0]),
        text_cls=SimpleNamespace(infer=wrappers[1]),
        text_rec=SimpleNamespace(session=wrappers[2]),
    )
    original = [w.session for w in wrappers]

    def factory(model, *, sess_options, providers, provider_options):
        assert sess_options.enable_cpu_mem_arena
        assert sess_options.intra_op_num_threads == 8
        assert providers == ["CPUExecutionProvider"]
        assert provider_options == [{"arena_extend_strategy": "kSameAsRequested"}]
        if model == "rec":
            raise ValueError("load failure")
        replacement = Session(model)
        constructed.append(replacement)
        return replacement

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=factory))
    with pytest.raises(ValueError, match="load failure"):
        enable_cpu_arena(backend)
    assert [w.session for w in wrappers] == original

    def success(model, **kwargs):
        return Session(model)

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=success))
    enable_cpu_arena(backend)
    assert [w.session._model_path for w in wrappers] == ["det", "cls", "rec"]
    assert all(w.session is not old for w, old in zip(wrappers, original, strict=True))


def test_cpu_arena_profile_is_opt_in():
    assert RapidOCRProvider(backend=lambda _: ([], [])).cpu_memory_arena is False


def test_provider_organization_digits_are_structural_not_identity_authority():
    from packages.claim_intelligence.models import (
        AuthorityState,
        Candidate,
        EvidenceFeatures,
        FieldNode,
    )
    from packages.claim_intelligence.normalization import normalize
    from packages.claim_intelligence.risk import RiskScorer

    value, valid = normalize("provider_name", "EXAMPLE CLINIC 24")
    assert value == "EXAMPLE CLINIC 24" and valid
    assert normalize("patient_name", value)[1] is False
    assert normalize("provider_name", "1234567890")[1] is False
    candidate = Candidate("known", value, features=EvidenceFeatures(format_valid=True))
    for authority in (
        AuthorityState.AUTHORITATIVE_NOT_AVAILABLE,
        AuthorityState.AUTHORITATIVE_CONFLICT,
    ):
        field = FieldNode("provider_name", [candidate], authority_state=authority)
        assert RiskScorer().score(field, candidate).action == "REVIEW_SHADOW"


def test_noncanonical_npi_checksum_is_discovery_not_provider_identity():
    from packages.claim_intelligence.discovery import NoncanonicalDiscovery
    from packages.claim_intelligence.document import DocumentPage, Token

    def token(text, box):
        return Token(text, text, box, 0.99, "test", "page", str(box), "inv", "source", "crop")

    page = DocumentPage(
        "page",
        "package",
        "OTHER_CLAIM_FORM",
        "NOT_VERIFIED",
        1000,
        1000,
        "UNKNOWN",
        (token("NPI", (100, 100, 140, 120)), token("1234567893", (145, 100, 235, 120))),
    )
    result = NoncanonicalDiscovery().extract(page)
    assert result.candidates["provider_npi"][0].normalized_value == "1234567893"
    assert not result.production_authority and result.authority == "UNVERIFIED_DISCOVERY"
