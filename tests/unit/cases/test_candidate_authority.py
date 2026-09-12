"""Synthetic authority contracts and immutable candidate binding; no real labels."""
import copy
import json
from pathlib import Path

import pytest

from evaluation import candidate_runtime_freeze as freeze
from evaluation.validation_blockers import classify_validation
from packages.evidence_decision import FieldDisposition
from packages.runtime_profile import DecisionServiceFactory
from packages.semantic_authority import AuthorityState, resolve_authority
from tests.unit.cases.test_evidence_decision_service import context


def scoped_context():
    return context(claim_id="claim", document_id="document", page_id="page",
        form_identity_authority={"status":"VERIFIED", "document_id":"document", "document_family":"CMS1500",
                                 "page_ids":["page"], "evidence_sha256":"a"*64, "policy_version":"synthetic-v1"},
        claim_membership_authority={"governed":True, "complete_claim_membership_confirmed":True,
            "boundary_provenance":{"owner_approval_receipt_sha256":"b"*64,"approved_csv_sha256":"c"*64},
            "claims":{"claim":{"page_ids":["page"],"claim_form_page_ids":["page"],"attachment_page_ids":[],
                "documents":{"document":{"page_ids":["page"],"boundary":"CONFIRMED","boundary_provenance":"synthetic"}}}}})


def test_scoped_authority_is_verified_without_granting_acceptance():
    source = scoped_context()
    result = resolve_authority(source, ())
    assert result.state is AuthorityState.VERIFIED and not result.blockers
    assert len(result.policy_sha256) == 64


@pytest.mark.parametrize("change,state", [
    ({"document_id":"other"}, AuthorityState.FORM_IDENTITY_REQUIRED),
    ({"page_id":"other"}, AuthorityState.FORM_IDENTITY_REQUIRED),
    ({"claim_id":"other"}, AuthorityState.MEMBERSHIP_REQUIRED),
    ({"claim_membership_authority":{}}, AuthorityState.MEMBERSHIP_REQUIRED),
    ({"source_role":"ATTACHMENT"}, AuthorityState.AMBIGUOUS),
    ({"semantic_state":"SOURCE_ABSENT"}, AuthorityState.AMBIGUOUS),
    ({"semantic_state":"DERIVED_UNVERIFIED"}, AuthorityState.AMBIGUOUS),
    ({"semantic_blockers":["PRINTED_DERIVED_DISAGREEMENT"]}, AuthorityState.AMBIGUOUS),
])
def test_scope_and_semantic_failures_cannot_verify(change,state):
    result = resolve_authority(scoped_context().model_copy(update=change), ())
    assert result.state is state


def test_authority_reports_all_missing_stages():
    result = resolve_authority(context(), ("AUTHORITATIVE_REFERENCE",))
    assert set(result.blockers) == {AuthorityState.FORM_IDENTITY_REQUIRED.value,
        AuthorityState.MEMBERSHIP_REQUIRED.value, AuthorityState.REFERENCE_REQUIRED.value}


def test_reference_requires_authorization_and_scope():
    from packages.evidence_decision import ReferenceEvidence
    from packages.evidence_router import ReferenceSourceState
    source = scoped_context()
    source.reference_source_state = ReferenceSourceState.AUTHORIZED
    source.reference = ReferenceEvidence(value="JANE DOE", verified=True, source="synthetic", version="1",
        reference_key="synthetic", snapshot_checksum="d"*64, matched_attributes=["synthetic"])
    assert resolve_authority(source, ("AUTHORITATIVE_REFERENCE",)).state is AuthorityState.VERIFIED
    source.reference.value = "DISTINCT IDENTITY"
    assert resolve_authority(source, ("AUTHORITATIVE_REFERENCE",)).state is AuthorityState.REFERENCE_REQUIRED


def test_production_decision_emits_authority_and_cannot_auto_accept_missing_scope():
    decision = DecisionServiceFactory.from_profile().evidence_decision.decide(context())
    assert decision.authority.state is AuthorityState.FORM_IDENTITY_REQUIRED
    assert decision.disposition not in {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED}
    assert decision.model_dump(mode="json")["authority"]["policy_sha256"] != "UNBOUND"


@pytest.mark.parametrize("reason,category", [("INVALID_ICD10_SYNTAX","FORMAT"), ("CHECKSUM_FAILURE","CHECKSUM"),
    ("INVALID_DATE","DATE"), ("EMPTY_VALUE","MISSING REQUIRED VALUE"), ("NEW_UNKNOWN_CODE","OTHER"),
    ("REFERENCE_LOOKUP_REQUIRED","REFERENCE LOOKUP"), ("TOTAL_MISMATCH","TOTAL RECONCILIATION")])
def test_validator_categories_do_not_confuse_syntax_with_lookup(reason, category):
    assert classify_validation([reason]) == [category]


def test_candidate_record_matches_git_and_preserves_historical_freeze():
    historical = freeze.ROOT / "docs/qualification/track_b_completion/track_a_freeze.json"
    before = historical.read_bytes()
    record = freeze.create()
    assert record["candidate_commit_sha"] == freeze.CANDIDATE
    assert len(record["bindings"]) == 7
    assert historical.read_bytes() == before
    assert freeze.readiness()["freeze_integrity"] == "PASS"


def test_candidate_record_cannot_be_overwritten(tmp_path, monkeypatch):
    record = {"synthetic":"original"}
    monkeypatch.setattr(freeze, "build", lambda root: copy.deepcopy(record))
    freeze.create(tmp_path)
    record["synthetic"] = "tampered"
    with pytest.raises(ValueError, match="IMMUTABLE"):
        freeze.create(tmp_path)
    assert json.loads((tmp_path/freeze.RECORD).read_text()) == {"synthetic":"original"}


def test_current_deployment_draft_is_bound_but_not_approved():
    import yaml

    from evaluation.track_b_preflight import preflight
    config = yaml.safe_load(Path("config/qualification/deployment_control.yaml").read_text())
    result = preflight(config, environ={}, checker=lambda *_: pytest.fail("must not probe"))
    assert result["status"] == "INVALID_CONTRACT"
    assert result["contract"]["checks"]["candidate_commit_sha"] == "VALID"
    assert result["contract"]["checks"]["candidate_pipeline_binding"] == "VALID"
