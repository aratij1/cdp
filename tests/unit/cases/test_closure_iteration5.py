"""Synthetic stage-boundary tests: reclassification never becomes release truth."""

from dataclasses import FrozenInstanceError, replace

import pytest

from evaluation.closure_iteration5 import scenarios
from packages.claim_intelligence.blockers import SourceCondition, assess_field
from packages.claim_intelligence.models import Candidate, CandidateEvidence, EvidenceFeatures
from packages.claim_intelligence.pipeline import LegacyFieldResult


def observed(name="member_id", value="EXAMPLE123", source="SPATIAL_EXTRACTION"):
    evidence = CandidateEvidence(
        source,
        0.99,
        "page",
        "crop",
        "region",
        source_id="source",
        provenance_id="invocation",
        bbox=(10, 20, 100, 40),
    )
    return Candidate(
        "synthetic-candidate",
        value,
        (evidence,),
        value,
        EvidenceFeatures(0.95, 0.99, 0.95, True),
        name,
    )


def legacy(name="member_id", blockers=("CANDIDATE_ASSEMBLY", "WRONG_CROP", "MISSING_CROP")):
    return LegacyFieldResult(
        name, None, False, (), blockers, ("AUTHORITATIVE_DATA_REQUIRED",), True, True, True
    )


def test_source_review_moves_owner_without_selecting_a_value_or_removing_authority():
    original = legacy()
    condition = SourceCondition(
        "member_id", "source", "SOURCE_OVERPRINT", "inspection", (1, 1, 100, 100)
    )
    result = assess_field(original, [], source_sha256="source", source_condition=condition)
    assert not result.technical and len(result.reclassified) == 3 and not result.resolved
    assert result.external == ("AUTHORITATIVE_DATA_REQUIRED", "SOURCE_REVIEW_REQUIRED")
    assert result.document_value is None and not result.production_authority
    assert not condition.release_truth and original.canonical_value is None
    with pytest.raises(FrozenInstanceError):
        condition.release_truth = True


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "different"},
        {"field_name": "provider_name"},
        {"inspection_id": ""},
        {"kind": "OCR_CONSENSUS"},
        {"pixel_region": (1, 1, 0, 0)},
        {"pixel_region": (1, 1, float("inf"), 3)},
    ],
)
def test_source_inspections_fail_closed_when_unbound(change):
    condition = SourceCondition(
        "member_id", "source", "SOURCE_OVERPRINT", "inspection", (1, 1, 100, 100)
    )
    with pytest.raises(ValueError):
        assess_field(
            legacy(), [], source_sha256="source", source_condition=replace(condition, **change)
        )


def test_source_review_cannot_remove_unrelated_software_or_safety_failure():
    original = legacy(blockers=("WRONG_CROP", "LLM_INVENTED_VALUE", "CLAIM_CONSISTENCY_CONFLICT"))
    condition = SourceCondition(
        "member_id", "source", "SOURCE_OVERPRINT", "inspection", (1, 1, 100, 100)
    )
    result = assess_field(original, [], source_sha256="source", source_condition=condition)
    assert result.technical == ("LLM_INVENTED_VALUE", "CLAIM_CONSISTENCY_CONFLICT")


def test_ocr_disagreement_alone_is_not_a_source_review_attestation():
    result = assess_field(
        legacy(), [observed(value="EXAMPLE123"), observed(value="OTHER123")], source_sha256="source"
    )
    assert result.technical == legacy().technical_blockers and not result.reclassified


@pytest.mark.parametrize("name,value", [("member_id", "EXAMPLE123"), ("relationship", "SELF")])
def test_unique_literal_atomic_recovery_repairs_acquisition_only(name, value):
    original = legacy(name)
    result = assess_field(original, [observed(name, value)], source_sha256="source")
    assert result.document_value == value and not result.technical and len(result.resolved) == 3
    assert result.external == original.evidence_blockers and not result.production_authority
    assert not result.reclassified and original.canonical_value is None


@pytest.mark.parametrize("change", ["weak", "unbound", "invalid", "competing"])
def test_weak_unbound_invalid_or_competing_candidates_do_not_clear_crop_failures(change):
    candidate = observed()
    if change == "weak":
        candidate = observed(source="WEAK_LABEL_DISCOVERY")
    if change == "unbound":
        candidate = replace(
            candidate, evidence=(replace(candidate.evidence[0], source_id="other"),)
        )
    if change == "invalid":
        candidate = replace(candidate, value="EXAMPLE123 / BAD")
    values = [candidate, observed(value="OTHER123")] if change == "competing" else [candidate]
    result = assess_field(legacy(), values, source_sha256="source")
    assert result.technical == legacy().technical_blockers and result.document_value is None


def test_member_invalid_extra_text_is_not_second_id_but_geometry_remains_required():
    valid = observed()
    invalid = replace(
        valid,
        candidate_id="invalid",
        value="EXAMPLE123 / EXTRA",
        normalized_value="EXAMPLE123 / EXTRA",
    )
    original = replace(
        legacy(),
        canonical_value=valid.value,
        candidates=(valid, invalid),
        technical_blockers=("CANDIDATE_AMBIGUITY",),
        wrong_crop=False,
        missing_crop=False,
    )
    result = assess_field(original, [valid], source_sha256="source")
    assert result.technical == () and result.resolved == ("CANDIDATE_AMBIGUITY",)
    assert result.external == original.evidence_blockers and result.document_value is None
    assert original.candidates[1].value == "EXAMPLE123 / EXTRA"
    for geometry in (None, 0.5, float("inf")):
        unknown = replace(valid, features=replace(valid.features, geometry_confidence=geometry))
        result = assess_field(
            replace(original, candidates=(unknown, invalid)), [valid], source_sha256="source"
        )
        assert result.technical == ("CANDIDATE_AMBIGUITY",)


def test_stp_scenarios_are_conditional_not_observed_release_performance():
    claims = [
        {"technical_distance": 0, "external_categories": ["MEMBER_AUTHORITY_REQUIRED"]},
        {"technical_distance": 1, "external_categories": []},
    ]
    report = {r["scenario"]: r for r in scenarios(claims)}
    assert report["CURRENT_EVIDENCE"]["potentially_stp_capable_claims"] == 0
    assert report["ALL_EXTERNAL_EVIDENCE_AVAILABLE"]["potentially_stp_capable_claims"] == 1
    assert report["ALL_EXTERNAL_EVIDENCE_AVAILABLE"]["production_qualified_claims_observed"] == 0
    assert not any(r["achieved"] for r in report.values())


def test_each_logical_fix_can_be_evaluated_against_same_baseline():
    original = legacy()
    candidate = observed()
    unchanged = assess_field(original, [candidate], source_sha256="source", enable_recovery=False)
    improved = assess_field(original, [candidate], source_sha256="source", enable_recovery=True)
    assert unchanged.technical == original.technical_blockers
    assert improved.technical == () and unchanged.external == improved.external
    assert original.canonical_value is None


def test_pipeline_rejects_duplicate_or_foreign_inspection_fields():
    from packages.claim_intelligence.discovery import DiscoveryResult
    from packages.claim_intelligence.pipeline import CDP2ShadowPipeline, LegacyResult

    field = legacy()
    original = LegacyResult("claim", (field,), "canonical-unchanged", "OTHER_CLAIM_FORM")
    inspection = SourceCondition(
        "member_id", "source", "SOURCE_OVERPRINT", "inspection", (1, 1, 10, 10)
    )
    pipeline = CDP2ShadowPipeline()
    for conditions in ((inspection, inspection), (replace(inspection, field_name="unknown"),)):
        with pytest.raises(ValueError):
            pipeline.assess_document_blockers(
                original, DiscoveryResult({}), source_sha256="source", source_conditions=conditions
            )
    assert original.canonical_sha256 == "canonical-unchanged"
