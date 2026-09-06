"""Synthetic tests for review-only label recovery; no benchmark labels embedded."""

from dataclasses import replace

import pytest

from packages.claim_intelligence.discovery import NoncanonicalDiscovery, select_recovery
from packages.claim_intelligence.document import DocumentPage, Token
from packages.claim_intelligence.models import AuthorityState, FieldNode
from packages.claim_intelligence.risk import RiskScorer


def page(label="PATICNTNAMF", value="EXAMPLE PERSON", neighbor=True):
    def token(text, box):
        return Token(
            text, text, box, 0.99, "synthetic", "page", str(box), "invocation", "source", "crop"
        )

    tokens = [token(label, (100, 100, 250, 130)), token(value, (110, 126, 240, 150))]
    if neighbor:
        tokens.append(token("DOB", (400, 100, 450, 130)))
    return DocumentPage(
        "page",
        "package",
        "OTHER_CLAIM_FORM",
        "NOT_VERIFIED",
        1000,
        1000,
        "SYNTHETIC",
        tuple(tokens),
    )


def test_approximate_label_returns_unchanged_value_without_acceptance():
    source = page()
    result = NoncanonicalDiscovery().extract(source)
    candidate = result.candidates["patient_name"][0]
    assert candidate.value == source.tokens[1].text
    assert all(e.source == "WEAK_LABEL_DISCOVERY" for e in candidate.evidence)
    assert candidate.evidence[0].bbox == source.tokens[1].bbox
    assert candidate.evidence[0].source_id == "source"
    assert candidate.features.anchor_confidence is None
    assert select_recovery("patient_name", [candidate], existing_value=None)[0] is None
    node = FieldNode(
        "patient_name", [candidate], authority_state=AuthorityState.AUTHORITATIVE_MATCH
    )
    decision = RiskScorer().score(node, candidate, deterministic_proof=True)
    assert not decision.extraction_supported and decision.action == "REVIEW_SHADOW"
    assert source.tokens[0].text == "PATICNTNAMF"
    assert not result.production_authority and not result.canonical_localization


@pytest.mark.parametrize("family", ["UNKNOWN", "CMS1500", "UB04"])
def test_approximate_label_never_authorizes_canonical_localization(family):
    assert not NoncanonicalDiscovery().extract(replace(page(), form_type=family)).candidates


def test_weak_labels_cannot_bootstrap_each_other():
    assert not NoncanonicalDiscovery().extract(page(neighbor=False)).candidates
    source = page()
    source = replace(
        source,
        tokens=(
            *source.tokens[:2],
            replace(source.tokens[2], text="MEMBER1D", normalized_text="MEMBER1D"),
        ),
    )
    assert not NoncanonicalDiscovery().extract(source).candidates


@pytest.mark.parametrize("label", ["PATIENTNAMEEXTRATEXT", "XXPATIENTNAMEXX", "DOBX"])
def test_no_substring_or_short_label_repair(label):
    assert not NoncanonicalDiscovery().extract(page(label=label)).candidates


def test_conflicting_label_assignments_fail_closed():
    extractor = NoncanonicalDiscovery()
    extractor.labels["PATICNTNOME"] = "insured_name"
    assert not extractor.extract(page()).candidates


def test_exact_compound_label_retains_only_observed_diagnosis_characters():
    source = page("DIAGNOSIS/ICD", "Z12.3")
    result = NoncanonicalDiscovery().extract(source)
    assert result.candidates["diagnosis"][0].value == "Z12.3"
    assert all(e.source == "SPATIAL_EXTRACTION" for e in result.candidates["diagnosis"][0].evidence)
    assert not NoncanonicalDiscovery().extract(page("DIAGNOSIS/ICD", "JY12.3")).candidates
    assert not NoncanonicalDiscovery().extract(page("PATIENTNAME/DOB", "EXAMPLE PERSON")).candidates


def test_weak_duplicate_does_not_contaminate_literal_candidate():
    source = page()
    exact_label = replace(
        source.tokens[0],
        text="PATIENT NAME",
        normalized_text="PATIENT NAME",
        bbox=(100, 350, 250, 380),
        source_region_id="literal-label",
    )
    exact_value = replace(
        source.tokens[1], bbox=(110, 380, 240, 410), source_region_id="literal-value"
    )
    result = NoncanonicalDiscovery().extract(
        replace(source, tokens=(*source.tokens, exact_label, exact_value))
    )
    candidate = result.candidates["patient_name"][0]
    assert all(e.source == "SPATIAL_EXTRACTION" for e in candidate.evidence)
    assert select_recovery("patient_name", [candidate], existing_value=None)[0] == candidate


def test_review_handoff_has_no_predictions_labels_or_authority(tmp_path):
    import json

    from evaluation.closure_iteration4 import prepare_review_handoff

    manifest = {
        "cohort_sha256": "synthetic",
        "creates_labels": False,
        "pages": [{"page_id": str(i), "package_id": str(i // 2)} for i in range(150)],
    }
    result = prepare_review_handoff(manifest, tmp_path)
    assert result["labels_created"] == 0 and result["pages"] == 150
    assert result["status"] == "AWAITING_INDEPENDENT_HUMAN_REVIEW"
    assert json.loads((tmp_path / "blind_manifest.json").read_text()) == manifest
    schema = json.loads((tmp_path / "review_response_schema.json").read_text())
    assert "authority" not in schema["properties"]
    assert not list(tmp_path.glob("*labels*"))
    with pytest.raises(ValueError):
        prepare_review_handoff({**manifest, "predictions": []}, tmp_path)
    manifest["pages"][0]["prediction"] = "FORBIDDEN"
    with pytest.raises(ValueError):
        prepare_review_handoff(manifest, tmp_path)
