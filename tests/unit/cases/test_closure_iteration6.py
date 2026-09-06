"""Synthetic tests for exact contextual authority and claim-level enablement."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest

from packages.claim_evidence.authoritative_snapshot import MatchStatus, load_snapshot
from packages.claim_evidence.enablement import (
    IdentityAuthorityProvider,
    MemberAuthorityProvider,
    ProviderAuthorityProvider,
    SourceBinding,
    SourceEvidenceProvider,
    SourceStatus,
)
from packages.claim_intelligence.enablement import (
    ClaimRequirements,
    evidence_scenario,
    minimum_enablement,
)


def snapshot(tmp_path, **changes):
    record = {
        "source_record_id": "synthetic-record",
        "effective_from": "2025-01-01",
        "effective_to": "2025-12-31",
        "member_id": "TEST123",
        "payer": "TEST_PAYER",
        "patient_name": "SYNTHETIC PERSON",
        "dob": "1980-01-01",
        "eligible": True,
        "npi": "SYNTHETIC_NPI",
        "provider_name": "SYNTHETIC CLINIC",
        "provider_role": "billing",
        "person_role": "patient",
        "name": "SYNTHETIC PERSON",
    }
    record.update(changes)
    payload = {
        "snapshot_id": "synthetic",
        "source_system": "TEST_ONLY",
        "dataset_version": "1",
        "effective_date": "2025-01-01",
        "created_at": "2025-01-01T00:00:00+00:00",
        "schema_version": "1.0",
        "records": [record],
    }
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps(payload))
    return load_snapshot(path)


def member_query():
    return {
        "member_id": "TEST123",
        "payer": "TEST_PAYER",
        "patient_name": "SYNTHETIC PERSON",
        "dob": "1980-01-01",
        "service_date": date(2025, 6, 1),
    }


def test_unconfigured_authority_never_implies_match():
    assert MemberAuthorityProvider().lookup(**member_query()).status == MatchStatus.NOT_AVAILABLE
    assert (
        ProviderAuthorityProvider()
        .lookup(npi="x", provider_name="x", role="billing", service_date=None)
        .status
        == MatchStatus.NOT_AVAILABLE
    )
    assert (
        IdentityAuthorityProvider()
        .lookup(
            member_id="x", payer="x", person_role="patient", name="x", dob="x", service_date=None
        )
        .status
        == MatchStatus.NOT_AVAILABLE
    )


def test_member_exact_match_has_provenance_but_no_release_authority(tmp_path):
    snap = snapshot(tmp_path)
    result = MemberAuthorityProvider(snap, expected_sha256=snap.sha256).lookup(**member_query())
    assert result.status == MatchStatus.MATCH and result.provenance_ids and result.snapshot_version
    assert (
        result.retrieved_at.tzinfo and not result.production_authority and not result.release_truth
    )
    with pytest.raises(FrozenInstanceError):
        result.production_authority = True


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"payer": "OTHER"}, MatchStatus.NO_MATCH),
        ({"patient_name": "DIFFERENT"}, MatchStatus.CONFLICT),
        ({"service_date": date(2026, 1, 1)}, MatchStatus.NOT_AVAILABLE),
        ({"service_date": None}, MatchStatus.NOT_AVAILABLE),
        ({"dob": ""}, MatchStatus.NOT_AVAILABLE),
    ],
)
def test_context_scope_conflict_and_validity_fail_closed(tmp_path, change, expected):
    snap = snapshot(tmp_path)
    query = {**member_query(), **change}
    assert (
        MemberAuthorityProvider(snap, expected_sha256=snap.sha256).lookup(**query).status
        == expected
    )


def test_missing_reference_context_and_negative_eligibility_never_match(tmp_path):
    for changes, expected in [
        ({"dob": None}, MatchStatus.NOT_AVAILABLE),
        ({"eligible": False}, MatchStatus.CONFLICT),
    ]:
        snap = snapshot(tmp_path, **changes)
        assert (
            MemberAuthorityProvider(snap, expected_sha256=snap.sha256)
            .lookup(**member_query())
            .status
            == expected
        )


def test_unpinned_and_duplicate_snapshot_fail_closed(tmp_path):
    snap = snapshot(tmp_path)
    assert (
        MemberAuthorityProvider(snap).lookup(**member_query()).status == MatchStatus.NOT_AVAILABLE
    )
    duplicate = replace(snap, records=(snap.records[0], snap.records[0]))
    assert (
        MemberAuthorityProvider(duplicate, expected_sha256=snap.sha256)
        .lookup(**member_query())
        .status
        == MatchStatus.CONFLICT
    )


def test_provider_role_and_identity_person_are_bound(tmp_path):
    snap = snapshot(tmp_path)
    provider = ProviderAuthorityProvider(snap, expected_sha256=snap.sha256)
    args = {
        "npi": "SYNTHETIC_NPI",
        "provider_name": "SYNTHETIC CLINIC",
        "role": "billing",
        "service_date": date(2025, 1, 1),
    }
    assert provider.lookup(**args).status == MatchStatus.MATCH
    assert provider.lookup(**{**args, "provider_name": "OTHER"}).status == MatchStatus.CONFLICT
    identity = IdentityAuthorityProvider(snap, expected_sha256=snap.sha256)
    args = {
        "member_id": "TEST123",
        "payer": "TEST_PAYER",
        "person_role": "patient",
        "name": "SYNTHETIC PERSON",
        "dob": "1980-01-01",
        "service_date": date(2025, 1, 1),
    }
    assert identity.lookup(**args).status == MatchStatus.MATCH
    assert identity.lookup(**{**args, "person_role": "subscriber"}).status == MatchStatus.NO_MATCH
    assert identity.lookup(**{**args, "person_role": "unknown"}).status == MatchStatus.NOT_AVAILABLE


def test_source_presence_does_not_resolve_source_conflict(tmp_path):
    path = tmp_path / "synthetic.txt"
    path.write_bytes(b"synthetic attachment")
    binding = SourceBinding(
        "package",
        "page",
        "attachment",
        path,
        hashlib.sha256(path.read_bytes()).hexdigest(),
        "boundary",
        ("region",),
    )
    args = {"package_id": "package", "page_id": "page", "attachment_id": "attachment"}
    result = SourceEvidenceProvider((binding,)).lookup(**args)
    assert result.status == SourceStatus.AVAILABLE
    assert (
        not result.resolves_source_review
        and not result.release_truth
        and not result.production_authority
    )
    assert SourceEvidenceProvider().lookup(**args).status == SourceStatus.NOT_AVAILABLE
    assert SourceEvidenceProvider((binding, binding)).lookup(**args).status == SourceStatus.CONFLICT
    assert (
        SourceEvidenceProvider((replace(binding, value_region_provenance_ids=()),))
        .lookup(**args)
        .status
        == SourceStatus.NOT_AVAILABLE
    )
    path.write_bytes(b"changed")
    assert SourceEvidenceProvider((binding,)).lookup(**args).status == SourceStatus.CONFLICT
    path.unlink()
    assert SourceEvidenceProvider((binding,)).lookup(**args).status == SourceStatus.NOT_AVAILABLE


def test_claim_combinations_do_not_double_count_fields_or_ignore_technical_blocks():
    claims = (
        ClaimRequirements("a", 0, frozenset({"MEMBER_AUTHORITY", "PROVIDER_AUTHORITY"})),
        ClaimRequirements("b", 1, frozenset({"MEMBER_AUTHORITY"})),
    )
    report = evidence_scenario(claims, frozenset({"MEMBER_AUTHORITY"}))
    assert report["evidence_capable_claims"] == 1 and report["potentially_stp_capable_claims"] == 0
    assert report["achieved_production_stp"] is None


def test_minimum_enablement_requires_source_review_for_six_of_twenty_claims():
    core = frozenset(
        {"MEMBER_AUTHORITY", "PROVIDER_AUTHORITY", "IDENTITY_AUTHORITY", "SOURCE_EVIDENCE"}
    )
    claims = tuple(
        ClaimRequirements(str(i), 0, core | ({"SOURCE_REVIEW"} if i < 6 else set()))
        for i in range(20)
    )
    result = minimum_enablement(claims)
    assert result["minimum_capability_count"] == 5 and len(result["minimum_paths"]) == 1
    assert evidence_scenario(claims, core)["potentially_stp_capable_claims"] == 14
    assert result["minimum_paths"][0]["potentially_stp_capable_claims"] == 20


def test_minimum_returns_all_ties_and_unreachable_target():
    claims = (
        ClaimRequirements("a", 0, frozenset({"MEMBER_AUTHORITY"})),
        ClaimRequirements("b", 0, frozenset({"PROVIDER_AUTHORITY"})),
    )
    assert len(minimum_enablement(claims, 0.5)["minimum_paths"]) == 2
    blocked = tuple(replace(c, technical_blockers=1) for c in claims)
    assert minimum_enablement(blocked)["status"] == "TARGET_NOT_REACHABLE"
    with pytest.raises(ValueError):
        minimum_enablement((claims[0], claims[0]))


@pytest.mark.parametrize(
    "name", ["member_id", "subscriber_id", "provider_name", "patient_name", "insured_name", "npi"]
)
def test_identity_extraction_success_survives_unavailable_authority(name):
    from packages.claim_intelligence.enablement import identity_review_state
    from packages.claim_intelligence.models import AuthorityState, ExtractionState, FieldNode

    node = FieldNode(name, extraction_state=ExtractionState.EXTRACTED_CONFIDENT)
    unavailable = MemberAuthorityProvider().lookup(**member_query())
    report = identity_review_state(node, unavailable, authority_required=True)
    assert report["extraction_state"] == "EXTRACTED_CONFIDENT"
    assert report["authority_state"] == "AUTHORITATIVE_NOT_AVAILABLE"
    assert report["production_decision"] == "REVIEW_REQUIRED"
    assert node.authority_state == AuthorityState.AUTHORITATIVE_NOT_AVAILABLE


def test_existing_authoritative_conflict_is_never_overridden(tmp_path):
    from packages.claim_intelligence.enablement import identity_review_state
    from packages.claim_intelligence.models import AuthorityState, FieldNode

    snap = snapshot(tmp_path)
    matched = MemberAuthorityProvider(snap, expected_sha256=snap.sha256).lookup(**member_query())
    node = FieldNode("member_id", authority_state=AuthorityState.AUTHORITATIVE_CONFLICT)
    report = identity_review_state(node, matched, authority_required=False)
    assert report["authority_state"] == "AUTHORITATIVE_CONFLICT"
    assert report["production_decision"] == "REVIEW_REQUIRED"


def test_record_mutation_after_adapter_configuration_fails_closed(tmp_path):
    snap = snapshot(tmp_path)
    provider = MemberAuthorityProvider(snap, expected_sha256=snap.sha256)
    snap.records[0].values["eligible"] = False
    assert provider.lookup(**member_query()).status != MatchStatus.MATCH


@pytest.mark.parametrize(
    "defect", ["semantic_change", "missing_page", "page_order", "empty_downstream"]
)
def test_latency_qualification_rejects_non_equivalent_repetitions(defect):
    from copy import deepcopy

    from evaluation.closure_iteration6 import qualify_latency

    keys = (
        "page_id",
        "package_id",
        "dimensions",
        "token_evidence_sha256",
        "text_geometry_sha256",
        "candidate_semantics_sha256",
        "downstream_semantics_sha256",
        "strict_family",
        "identity_confirmed",
        "canonical_localization_invoked",
    )
    pages = [{k: (str(i) if k == "page_id" else "synthetic") for k in keys} for i in range(12)]
    profile = {
        "experiments": [{"pages": deepcopy(pages)} for _ in range(4)],
        "session_constructions": 1,
    }
    if defect == "missing_page":
        profile["experiments"][2]["pages"].pop()
    elif defect == "page_order":
        profile["experiments"][2]["pages"].reverse()
    elif defect == "semantic_change":
        profile["experiments"][2]["pages"][0]["downstream_semantics_sha256"] = "changed"
    with pytest.raises(ValueError):
        qualify_latency(profile)
