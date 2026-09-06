from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from evaluation.cdp2_real_corpus import select_review
from packages.claim_intelligence.adjudication import bounded_selection, pricing_status
from packages.claim_intelligence.consistency import ClaimConsistencyEngine
from packages.claim_intelligence.document import DocumentPage, Token, adapt_ocr_tokens
from packages.claim_intelligence.models import (
    AuthorityState,
    Candidate,
    CandidateEvidence,
    ClaimGraph,
    EvidenceFeatures,
    FieldNode,
    ServiceLine,
)
from packages.claim_intelligence.normalization import calendar_date, money, normalize
from packages.claim_intelligence.pipeline import (
    CDP2ShadowPipeline,
    LegacyFieldResult,
    LegacyResult,
    assert_same_claims,
    graph_relationships,
    run_after_legacy,
    unlock,
)
from packages.claim_intelligence.provenance import independent
from packages.claim_intelligence.risk import RiskScorer
from packages.claim_intelligence.shadow import ShadowClaimResult
from packages.claim_intelligence.spatial import SpatialCandidateExtractor
from packages.claim_intelligence.telemetry import STAGES, OCRInvocationLedger, PerformanceProfile
from packages.domain.claim import Claim
from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRToken


def evidence(key="1"):
    return CandidateEvidence(
        "OCR",
        0.99,
        "page",
        "crop" + key,
        "region" + key,
        source_id="source",
        provenance_id="inv" + key,
    )


def candidate(key="1", value="AB123"):
    return Candidate(key, value, (evidence(key),), value, EvidenceFeatures(0.99, 0.99, 0.99, True))


def token(text, box, page_id="page"):
    return Token(text, text, box, 0.99, "rapidocr", page_id, str(box), "inv", "source", "crop")


def page(tokens=(), form="CMS1500", state="VERIFIED"):
    return DocumentPage("page", "package", form, state, 1000, 1000, "UNKNOWN", tuple(tokens), 0.99)


def test_document_adapter_retains_provenance_and_diagnostics_hide_text():
    box = BoundingBox(x0=1, y0=2, x1=30, y1=15, image_width=1000, image_height=1000)
    tokens = adapt_ocr_tokens(
        (OCRToken("PRIVATE OBSERVATION", 0.9, box),),
        page_id="page",
        source_id="source",
        engine="rapidocr",
        invocation_id="inv",
        crop_hash="crop",
    )
    p = page(tokens)
    assert tokens[0].bbox == (1, 2, 30, 15)
    assert "PRIVATE OBSERVATION" not in str(p.diagnostics())
    with pytest.raises(ValueError, match="MISMATCH"):
        page((replace(tokens[0], page_id="elsewhere"),))
    with pytest.raises(ValueError, match="PROVENANCE"):
        replace(tokens[0], provenance_id="")


def test_spatial_name_assembly_reading_order_and_alternatives():
    tokens = [
        token("PATIENT'S NAME", (100, 100, 220, 112)),
        token("Person", (154, 125, 210, 139)),
        token("Sample", (100, 125, 150, 139)),
        token("Alternative", (100, 145, 190, 159)),
    ]
    result = SpatialCandidateExtractor().extract(page(tokens))
    values = [c.value for c in result["patient_name"]]
    assert "Sample Person" in values and "Alternative" in values
    assert all("PATIENT" not in v for v in values)


def test_name_numeric_and_neighbor_exclusion():
    extractor = SpatialCandidateExtractor()
    assert not extractor.extract(
        page([token("PATIENT'S NAME", (100, 100, 220, 112)), token("123456", (100, 125, 170, 140))])
    )
    assert not extractor.extract(
        page(
            [
                token("PATIENT'S NAME", (100, 100, 220, 112)),
                token("DOB", (100, 120, 135, 133)),
                token("Neighbor", (100, 140, 190, 154)),
            ]
        )
    ).get("patient_name")


@pytest.mark.parametrize(
    "form,state",
    [("OTHER_CLAIM_FORM", "VERIFIED"), ("UNKNOWN", "VERIFIED"), ("UB04", "NOT_VERIFIED")],
)
def test_identity_gate_cannot_be_bypassed(form, state):
    assert not SpatialCandidateExtractor().extract(
        page(
            [token("MEMBER ID", (100, 100, 200, 112)), token("AB123", (100, 125, 170, 140))],
            form,
            state,
        )
    )


def test_member_extraction_and_external_authority_are_separate():
    f = FieldNode(
        "member_id", [candidate()], authority_state=AuthorityState.AUTHORITATIVE_NOT_AVAILABLE
    )
    result = RiskScorer().score(f, f.candidates[0])
    assert result.extraction_supported
    assert result.action == "REVIEW_SHADOW"
    assert "AUTHORITY_NOT_AVAILABLE" in result.reasons
    assert (
        RiskScorer()
        .score(replace(f, authority_state=AuthorityState.AUTHORITATIVE_CONFLICT), f.candidates[0])
        .risk_band
        == "HIGH"
    )


def charge_claim():
    return ClaimGraph(
        "claim",
        "UB04",
        {"total_charge": FieldNode("total_charge", [candidate("h", "0.30")])},
        [
            ServiceLine("1", charge="0.10", evidence=(evidence("1"),)),
            ServiceLine("2", charge="0.20", evidence=(evidence("2"),)),
        ],
        service_lines_complete=True,
    )


def test_decimal_arithmetic_proof():
    result = ClaimConsistencyEngine().total_charge(charge_claim())
    assert result[0].verdict == "PROOF" and result[0].authority == "ARITHMETIC_EXACT"
    assert "0.30" not in result[0].reason
    assert money("0.00") == Decimal("0.00")


@pytest.mark.parametrize(
    "change", ["incomplete", "duplicate", "missing", "same_crop", "currency", "unreadable", "sign"]
)
def test_charge_fails_closed(change):
    c = charge_claim()
    if change == "incomplete":
        c.service_lines_complete = False
    if change == "duplicate":
        c.service_lines[1] = replace(c.service_lines[1], line_id="1")
    if change == "missing":
        c.service_lines[1] = replace(c.service_lines[1], charge=None)
    if change == "same_crop":
        c.service_lines[1] = replace(c.service_lines[1], evidence=(evidence("1"),))
    if change == "currency":
        c.service_lines[1] = replace(c.service_lines[1], currency="EUR")
    if change == "unreadable":
        c.service_lines[1] = replace(c.service_lines[1], readable=False)
    if change == "sign":
        c.service_lines[1] = replace(c.service_lines[1], sign_unambiguous=False)
    assert not ClaimConsistencyEngine().total_charge(c)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1,00", "1.001", "O.20"])
def test_money_never_guesses(value):
    assert money(value) is None


def test_dates_chronology_unknown_and_unusual_age():
    c = ClaimGraph(
        "claim",
        "CMS1500",
        {"patient_dob": FieldNode("patient_dob", [candidate("d", "1990-01-01")])},
    )
    engine = ClaimConsistencyEngine()
    assert engine.dob(c)[0].verdict == "UNKNOWN"
    c.service_lines = [ServiceLine("1", service_date="1989-01-01")]
    assert engine.dob(c)[0].verdict == "CONFLICT"
    c.service_lines = [ServiceLine("1", service_date="2024-01-01")]
    assert engine.dob(c)[0].verdict == "PROOF"
    c.fields["patient_dob"].candidates = [candidate("d", "1880-01-01")]
    assert engine.dob(c)[0].verdict == "UNKNOWN"
    assert calendar_date("01/01/24") is None


def test_statement_period_and_applicable_admission_constraints():
    c = ClaimGraph(
        "claim",
        "UB04",
        service_lines=[ServiceLine("1", service_date="2024-02-29")],
        statement_start="2024-02-01",
        statement_end="2024-02-29",
    )
    e = ClaimConsistencyEngine()
    assert e.service_dates(c)[0].verdict == "PROOF"
    c.statement_end = "2024-02-28"
    assert e.service_dates(c)[0].verdict == "CONFLICT"
    c.statement_end = "2024-02-29"
    c.admission_constraints_applicable = True
    assert e.service_dates(c)[0].verdict == "UNKNOWN"
    c.admission_date, c.discharge_date = "2024-02-01", "2024-02-15"
    assert e.service_dates(c)[0].verdict == "CONFLICT"


@pytest.mark.parametrize(
    "value,expected", [(" z00 0 ", "Z00.0"), ("Z00.0", "Z00.0"), ("ZO0.0", None), ("Z00..0", None)]
)
def test_conservative_diagnosis(value, expected):
    normalized, valid = normalize("principal_diagnosis", value)
    assert (normalized if valid else None) == expected


def test_relationships_and_pointer_contradictions():
    c = ClaimGraph(
        "claim",
        "CMS1500",
        {"patient_name": FieldNode("patient_name")},
        [ServiceLine("1", diagnosis_pointer="3")],
        diagnosis_positions=("1", "2"),
    )
    edges = graph_relationships(c)
    assert ("Patient", "has_field", "patient_name") in edges
    assert ("Claim", "has_service_line", "1") in edges
    assert ClaimConsistencyEngine().relationships(c)[0].verdict == "CONFLICT"


def test_same_crop_different_engine_never_independent():
    a = evidence("1")
    assert not independent(a, replace(evidence("2"), crop_hash=a.crop_hash, source="other_ocr"))
    assert not independent(a, replace(evidence("2"), localization_region=a.localization_region))
    assert independent(a, evidence("2"))


def test_ocr_confidence_alone_and_critical_conflicts_force_review():
    c = replace(candidate(), features=EvidenceFeatures())
    f = FieldNode(
        "member_id", [c], critical=True, authority_state=AuthorityState.AUTHORITATIVE_NOT_REQUIRED
    )
    assert RiskScorer().score(f, c).action == "REVIEW_SHADOW"
    r = RiskScorer().score(f, candidate(), deterministic_conflict=True)
    assert r.risk_band == "HIGH" and "DETERMINISTIC_CONFLICT" in r.reasons


def test_same_claim_boundary_and_technical_unlock_without_production_unlock():
    c = candidate()
    legacy = LegacyResult(
        "claim",
        (
            LegacyFieldResult(
                "member_id",
                "AB123",
                False,
                (c,),
                ("CANDIDATE_ASSEMBLY",),
                ("AUTHORITATIVE_DATA_REQUIRED",),
                True,
            ),
        ),
        "hash",
        "CMS1500",
    )
    graph = ClaimGraph(
        "claim", "CMS1500", {"member_id": FieldNode("member_id", [c])}, form_identity_confirmed=True
    )
    before = repr(legacy)
    result = CDP2ShadowPipeline().compare(legacy, graph)
    assert result.legacy_metrics["technical_blockers"] == 1
    assert result.cdp2_metrics["technical_blockers"] == 0
    assert result.cdp2_metrics["production_unlock_distance"] == 1
    assert result.cdp2_metrics["engineering_unlockable"]
    assert not result.cdp2_metrics["production_unlockable"]
    assert repr(legacy) == before
    assert len(graph.fields["member_id"].candidates) == 1
    with pytest.raises(ValueError):
        assert_same_claims((legacy,), (replace(result.cdp2, claim_id="wrong"),))
    with pytest.raises(ValueError):
        assert_same_claims((legacy, legacy), (result.cdp2, result.cdp2))
    assert not unlock(0, 0, 0)["production_unlockable"]


def test_canonical_result_is_returned_unchanged():
    claim = Claim(
        document_id=uuid4(),
        tenant_id="test",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1",
    )
    before = claim.model_dump(mode="json")
    calls = []

    def legacy():
        calls.append(1)
        return claim

    result, comparison = run_after_legacy(legacy, ())
    assert result is claim and calls == [1]
    assert result.model_dump(mode="json") == before
    assert not comparison.runtime_authority
    with pytest.raises(TypeError):
        ShadowClaimResult("x", (), 0, 0, 0, 0, production_authority=True)


def test_invocation_ledger_and_profiler():
    ledger = OCRInvocationLedger()
    calls = []

    def invoke():
        calls.append(1)
        return ("tokens",)

    assert ledger.full_page("key", invoke) == ledger.full_page("key", invoke)
    assert len(calls) == ledger.full_page_ocr_calls == 1
    with pytest.raises(ValueError):
        ledger.full_page("different", invoke)
    with pytest.raises(ValueError):
        ledger.use_validated_cache("key", (), provenance_valid=False)
    with pytest.raises(ValueError):
        ledger.regional(invoke, unresolved=False)
    ledger.regional(invoke, unresolved=True)
    assert ledger.regional_ocr_calls == 1
    profile = PerformanceProfile()
    with profile.measure("claim_graph_ms"):
        pass
    d = profile.diagnostics()
    assert set(STAGES) <= d.keys()
    assert d["total_ms"] >= d["claim_graph_ms"] >= 0
    assert d["full_page_ocr_ms"] is None


def test_llm_cannot_create_values_or_truth():
    c = candidate()
    assert bounded_selection(c.candidate_id, (c,)) is c
    assert bounded_selection("NONE", (c,)) is None
    with pytest.raises(ValueError):
        bounded_selection("invented", (c,))
    assert pricing_status() == "PRICING_NOT_CONFIGURED"


def test_active_learning_deterministic_blind_and_package_disjoint():
    records = [
        {
            "package_id": f"pkg{i // 3}",
            "source_page_id": f"page{i}",
            "candidate_class": "CMS1500" if i % 2 else "UB04",
            "classification_confidence": 0.5,
        }
        for i in range(15)
    ]
    a = select_review(records, {"pkg0"}, 8)
    b = select_review(list(reversed(records)), {"pkg0"}, 8)
    assert a == b
    assert all(set(r) == {"page_id", "package_id"} for r in a["human_review_view"])
    assert not a["creates_labels"] and not a["package_leakage_with_operational_replay"]


def test_three_false_ub04_canaries():
    from evaluation.strict_identity_cached_replay import _canaries
    from packages.document_routing import MultiSignalRouter

    canaries = _canaries(MultiSignalRouter.load())
    assert len(canaries) == 3
    assert all(c["ub04_rejected"] and c["ub04_localization_authorizations"] == 0 for c in canaries)


def test_shadow_failure_does_not_interrupt_canonical_delivery(monkeypatch):
    claim = Claim(
        document_id=uuid4(),
        tenant_id="test",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1",
    )
    before = claim.model_dump(mode="json")

    def fail(*args, **kwargs):
        raise ValueError("PRIVATE SOURCE VALUE")

    monkeypatch.setattr(CDP2ShadowPipeline, "compare", fail)
    canonical, result = run_after_legacy(lambda: claim, ())
    assert canonical.model_dump(mode="json") == before
    assert result.status == "SHADOW_FAILED_CANONICAL_UNCHANGED"
    assert "PRIVATE SOURCE VALUE" not in repr(result)
    assert not result.runtime_authority


def test_repeated_agreement_between_retained_candidates_requires_independence():
    a, b = candidate("a", "2024-01-01"), candidate("b", "2024-01-01")
    graph = ClaimGraph("claim", "CMS1500", {"service_date": FieldNode("service_date", [a, b])})
    proofs = [
        r
        for r in ClaimConsistencyEngine().evaluate(graph)
        if r.rule_id == "REPEATED_INDEPENDENT_EXACT"
    ]
    assert len(proofs) == 2
    graph.fields["service_date"].candidates[1] = replace(
        b, evidence=(replace(evidence("b"), crop_hash=evidence("a").crop_hash),)
    )
    assert not [
        r
        for r in ClaimConsistencyEngine().evaluate(graph)
        if r.rule_id == "REPEATED_INDEPENDENT_EXACT"
    ]


def test_cross_field_contradiction_is_not_ignored():
    c = replace(candidate(), features=EvidenceFeatures(0.99, 0.99, 0.99, True, False))
    f = FieldNode("member_id", [c], authority_state=AuthorityState.AUTHORITATIVE_NOT_REQUIRED)
    assert RiskScorer().score(f, c).action == "REVIEW_SHADOW"


def test_canonical_service_line_provenance_and_explicit_completeness():
    from packages.claim_intelligence.pipeline import canonical_adapter
    from packages.domain.claim import ServiceLine as CanonicalLine
    from packages.domain.enums import ExtractionMethod
    from packages.domain.extraction import ExtractedField, FieldEvidence
    from packages.ocr.provenance import EvidenceProvenance

    def extracted(name, key):
        box = BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100)
        observation = FieldEvidence(
            source=ExtractionMethod.REGIONAL_RAPIDOCR,
            raw_text="10.00",
            confidence=0.99,
            provenance=EvidenceProvenance(
                page_sha256="page",
                document_sha256="document",
                crop_sha256=key,
                localization_region_id=key,
                invocation_id=key,
            ),
        )
        return ExtractedField(
            field_name=name,
            raw_value="10.00",
            confidence=0.99,
            page_number=1,
            bounding_box=box,
            extraction_method=ExtractionMethod.REGIONAL_RAPIDOCR,
            candidates=[observation],
        )

    claim = Claim(
        document_id=uuid4(),
        tenant_id="test",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1",
        header_fields=[extracted("total_charge", "header")],
        service_lines=[
            CanonicalLine(
                line_number=1,
                charge_amount=Decimal("10.00"),
                fields=[extracted("charge_amount", "line")],
            )
        ],
    )
    _, missing = canonical_adapter(claim, ())
    assert not ClaimConsistencyEngine().total_charge(missing)
    _, complete = canonical_adapter(claim, (), service_lines_complete=True)
    assert ClaimConsistencyEngine().total_charge(complete)[0].verdict == "PROOF"
    assert any("@" in key for key in complete.fields)
