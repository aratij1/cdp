from dataclasses import replace

import pytest

from packages.claim_intelligence.discovery import NoncanonicalDiscovery
from packages.claim_intelligence.document import DocumentPage, Token


def token(text, box):
    return Token(
        text, text, box, 0.99, "synthetic", "page", str(box), "invocation", "source", "crop"
    )


@pytest.mark.parametrize(
    "field,label,value",
    [
        ("patient_name", "PATIENT NAME", "EXAMPLE PERSON"),
        ("patient_dob", "DOB", "01/02/2000"),
        ("member_id", "MEMBER ID", "EXAMPLE123"),
        ("total_charge", "TOTAL CHARGE", "123.45"),
    ],
)
def test_discovery_recovers_label_offset_without_source_or_authority_changes(field, label, value):
    page = DocumentPage(
        "page",
        "package",
        "OTHER_CLAIM_FORM",
        "NOT_VERIFIED",
        1000,
        1000,
        "SYNTHETIC",
        (token(label, (100, 100, 220, 120)), token(value, (85, 118, 210, 140))),
    )
    regions = []
    result = NoncanonicalDiscovery().extract(page, regions)
    assert result.candidates[field]
    assert result.candidates[field][0].value == value
    assert not result.production_authority and not result.canonical_localization
    assert regions and regions[0]["reason"] == "OBSERVED_LABEL_NEIGHBORHOOD"
    assert page.tokens[1].text == value
    assert not NoncanonicalDiscovery().extract(replace(page, form_type="UNKNOWN")).candidates


def test_discovery_does_not_expand_indefinitely_left_or_into_label_row():
    anchor = token("MEMBER ID", (100, 100, 220, 120))
    for value in (
        token("EXAMPLE123", (10, 122, 70, 140)),
        token("EXAMPLE123", (110, 101, 180, 115)),
    ):
        page = DocumentPage(
            "page",
            "package",
            "OTHER_CLAIM_FORM",
            "NOT_VERIFIED",
            1000,
            1000,
            "SYNTHETIC",
            (anchor, value),
        )
        assert not NoncanonicalDiscovery().extract(page).candidates


@pytest.mark.parametrize("name", ["patient_name", "insured_name", "provider_name"])
def test_name_equivalence_removes_only_representation_ambiguity(name):
    from packages.claim_intelligence.models import (
        AuthorityState,
        Candidate,
        ClaimGraph,
        EvidenceFeatures,
        FieldNode,
    )
    from packages.claim_intelligence.pipeline import (
        CDP2ShadowPipeline,
        LegacyFieldResult,
        LegacyResult,
    )
    from packages.claim_intelligence.risk import RiskScorer

    a = Candidate("a", "EXAMPLE PERSON", features=EvidenceFeatures(format_valid=True))
    b = Candidate("b", "EXAMPLEPERSON", features=EvidenceFeatures(format_valid=True))
    node = FieldNode(name, [a, b], authority_state=AuthorityState.AUTHORITATIVE_NOT_AVAILABLE)
    decision = RiskScorer().score(node, a)
    assert "CANDIDATE_AMBIGUITY" not in decision.reasons
    assert "AUTHORITY_NOT_AVAILABLE" in decision.reasons
    assert decision.action == "REVIEW_SHADOW"  # Missing provenance still blocks acceptance.
    legacy = LegacyResult(
        "claim",
        (
            LegacyFieldResult(
                name,
                a.value,
                False,
                (a, b),
                ("CANDIDATE_AMBIGUITY",),
                ("AUTHORITATIVE_DATA_REQUIRED",),
            ),
        ),
        "immutable",
        "CMS1500",
    )
    graph = ClaimGraph("claim", "CMS1500", {name: node})
    result = CDP2ShadowPipeline().compare(legacy, graph)
    assert result.cdp2_metrics["technical_unlock_distance"] == 0
    assert result.cdp2_metrics["production_unlock_distance"] == 1
    assert not result.cdp2_metrics["production_unlockable"]
    assert result.legacy is legacy and result.legacy.canonical_sha256 == "immutable"
    assert a.value == "EXAMPLE PERSON" and b.value == "EXAMPLEPERSON"
    node.candidates.append(
        Candidate("c", "DIFFERENT PERSON", features=EvidenceFeatures(format_valid=True))
    )
    assert "CANDIDATE_AMBIGUITY" in RiskScorer().score(node, a).reasons


def test_comparison_keys_do_not_turn_labels_or_member_separators_into_agreement():
    from packages.claim_intelligence.normalization import comparison_key

    assert comparison_key("patient_name", "PATIENT NAME EXAMPLE") != comparison_key(
        "patient_name", "EXAMPLE"
    )
    assert comparison_key("member_id", "AB-123") != comparison_key("member_id", "AB123")


@pytest.mark.parametrize(
    "label,value,field",
    [("DOB", "01/02/2000", "patient_dob"), ("TOTAL CHARGE", "123.45", "total_charge")],
)
def test_numeric_discovery_excludes_flags_without_character_substitution(label, value, field):
    page = DocumentPage(
        "page",
        "package",
        "OTHER_CLAIM_FORM",
        "NOT_VERIFIED",
        1000,
        1000,
        "SYNTHETIC",
        (
            token(label, (100, 100, 220, 120)),
            token(value, (100, 130, 190, 150)),
            token("M", (200, 130, 210, 150)),
        ),
    )
    result = NoncanonicalDiscovery().extract(page)
    assert result.candidates[field][0].value == value
    invalid = replace(page, tokens=(page.tokens[0], token("1O.00", (100, 130, 190, 150))))
    assert not NoncanonicalDiscovery().extract(invalid).candidates


def test_recovery_selection_is_shadow_only_unique_and_preserves_existing_value():
    from packages.claim_intelligence.discovery import select_recovery
    from packages.claim_intelligence.models import Candidate, EvidenceFeatures
    from packages.claim_intelligence.spatial import candidate_from_tokens

    a = candidate_from_tokens(
        "patient_name",
        [token("EXAMPLE PERSON", (100, 130, 200, 150))],
        anchor_confidence=0.99,
        geometry_confidence=0.5,
    )
    b = candidate_from_tokens(
        "patient_name",
        [token("DIFFERENT PERSON", (100, 160, 200, 180))],
        anchor_confidence=0.99,
        geometry_confidence=0.5,
    )
    selected, reasons = select_recovery("patient_name", [a], existing_value=None)
    assert selected is a and "SHADOW_ONLY" in reasons
    assert "NAME_STRUCTURALLY_VALID" in reasons
    assert select_recovery("patient_name", [a, b], existing_value=None)[0] is None
    assert select_recovery("patient_name", [a], existing_value="EXISTING PERSON")[0] is None
    assert select_recovery("unrecognized", [a], existing_value=None)[0] is None
    unsupported = Candidate(
        "unsupported",
        "EXAMPLE PERSON",
        features=EvidenceFeatures(format_valid=True),
        field_name="patient_name",
    )
    assert select_recovery("patient_name", [unsupported], existing_value=None)[0] is None
    assert select_recovery("provider_name", [a], existing_value=None)[0] is None
