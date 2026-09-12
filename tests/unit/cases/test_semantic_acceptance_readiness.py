"""Adversarial synthetic contracts only. These are not Track B truth or measurements."""
from __future__ import annotations

from dataclasses import replace

import pytest

from packages.claim_decision import ClaimDecisionService, ClaimDisposition
from packages.claim_evidence.charge_reconciliation import reconcile_total
from packages.claim_intelligence.normalization import comparison_key
from packages.evidence_decision import EvidenceDecisionService, FieldDisposition
from packages.real_data_evaluation.blind_workflow import content_digest
from packages.semantic_fields import (
    SemanticFieldState,
    SourceReference,
    infer_same_as_state,
    membership_authority_blockers,
    resolve_same_reference,
)
from tests.unit.cases.test_claim_decision_service import _context
from tests.unit.cases.test_evidence_decision_service import candidate, context
from tests.unit.cases.test_real_release_scoring import inputs, score, seal


def chain():
    return {"insured": SourceReference("claim", "SAME", ("printed:same",), ("patient",)),
            "patient": SourceReference("claim", "SYNTHETIC", ("printed:patient",))}


def test_explicit_same_preserves_original_and_entire_chain():
    result = resolve_same_reference("insured", "claim", chain(), owner_approved_complete=True)
    assert result.validated and result.output_value == "SYNTHETIC"
    assert result.source_value == "SAME"
    assert result.evidence_references == ("printed:same", "printed:patient")


@pytest.mark.parametrize("failure", ["cycle", "missing", "ambiguous", "cross_claim", "no_evidence", "no_owner"])
def test_same_invalid_authority_never_resolves(failure):
    fields = chain()
    if failure == "cycle": fields["patient"] = SourceReference("claim", "SAME", ("p",), ("insured",))
    if failure == "missing": fields.pop("patient")
    if failure == "ambiguous": fields["insured"] = replace(fields["insured"], refers_to=("patient", "other"))
    if failure == "cross_claim": fields["patient"] = replace(fields["patient"], claim_id="other")
    if failure == "no_evidence": fields["patient"] = replace(fields["patient"], evidence=())
    result = resolve_same_reference("insured", "claim", fields, owner_approved_complete=failure != "no_owner")
    assert not result.validated and result.output_value is None


def test_self_relationship_and_blank_never_manufacture_same():
    result = infer_same_as_state(field_name="insured", source_value="", counterpart_value="SYNTHETIC",
                                relationship_code="01", counterpart=SemanticFieldState.SAME_AS_PATIENT,
                                evidence_references=("relationship", "counterpart"))
    assert not result.validated


@pytest.mark.parametrize("left,right", [("ANN A", "ANNA"), ("ROBERT DOE", "BOB DOE"),
                                        ("DOE JANE", "JANE DOE"), ("JANE DOE", "JANE D0E")])
def test_identity_components_nicknames_order_and_ocr_substitution_are_not_aliases(left, right):
    assert comparison_key("patient_name", left) != comparison_key("patient_name", right)


@pytest.mark.parametrize("left,right", [("00123", "123"), ("00123A", "00123"),
                                        ("AB-123", "AB123"), ("AB  123", "AB 123"), ("ABO123", "AB0123")])
def test_member_id_characters_and_presentation_require_authority(left, right):
    assert comparison_key("insured_id_number", left) != comparison_key("insured_id_number", right)


@pytest.mark.parametrize("change,reason", [
    ({"semantic_state":"SOURCE_ABSENT"}, "PRINTED_FIELD_SOURCE_AUTHORITY_REQUIRED"),
    ({"semantic_state":"DERIVED_UNVERIFIED"}, "PRINTED_FIELD_SOURCE_AUTHORITY_REQUIRED"),
    ({"source_role":"ATTACHMENT"}, "ATTACHMENT_CANNOT_OVERRIDE_CLAIM_FORM"),
    ({"semantic_blockers":["PRINTED_DERIVED_DISAGREEMENT"]}, "PRINTED_DERIVED_DISAGREEMENT"),
    ({"candidates":[candidate("rapidocr", "SAME")]}, "EXPLICIT_SAME_REFERENCE_REVIEW_REQUIRED"),
])
def test_semantic_blocker_reaches_canonical_field_hitl(change, reason):
    decision = EvidenceDecisionService(route_mode="evaluation").decide(context(**change))
    assert decision.disposition is FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert reason in decision.reason_codes


def test_absent_and_disagreeing_totals_remain_separate():
    absent = reconcile_total(None, ["10.00", "20.00"])
    assert absent.reported_total is None and not absent.safe
    conflict = reconcile_total("25.00", ["10.00", "20.00"])
    assert str(conflict.reported_total) == "25.00" and str(conflict.calculated_sum) == "30.00"
    assert not conflict.safe


@pytest.mark.parametrize("failure", ["owner", "incomplete", "duplicate", "unbound", "attachment"])
def test_membership_and_attachment_ambiguity_block_safe(failure):
    truth, raw, membership = inputs()
    member = membership["claims"]["synthetic-claim"]
    if failure == "owner": membership["boundary_provenance"].pop("owner_approval_receipt_sha256")
    if failure == "incomplete": membership["complete_claim_membership_confirmed"] = False
    if failure == "duplicate": member["page_ids"].append("synthetic-page")
    if failure == "unbound": member["documents"] = {}
    if failure == "attachment": member["attachment_page_ids"] = ["adjacent-unowned-page"]
    assert membership_authority_blockers(membership, "synthetic-claim")
    truth["membership_sha256"] = content_digest(membership)
    seal(truth, "truth_sha256")
    with pytest.raises(ValueError): score(truth, raw, membership)


def test_runtime_does_not_claim_truth_verified_safe():
    service = ClaimDecisionService.load()
    decision = service.decide(_context(service))
    assert decision.disposition is ClaimDisposition.STP_STANDARD
    assert decision.runtime_evidence_safe and not decision.stp_safe
    assert decision.qualification_status == "NOT_EVALUATED"


def test_wrong_required_field_preserves_runtime_stp_but_is_false_safe():
    truth, raw, membership = inputs()
    raw["claims"]["synthetic-claim"]["decision"] = "STP_STANDARD"
    raw["fields"][0]["value"] = "WRONG"
    result = score(truth, raw, membership)["raw"]
    assert result["runtime_stp"] == 1 and result["stp_safe"] == 0
    assert result["false_stp_claims"] == 1 and result["critical_false_accepts"] == 1


@pytest.mark.parametrize("failure", ["human", "critical", "evidence", "output", "semantic", "field_semantic", "absent"])
def test_each_missing_safe_gate_blocks_truth_verified_stp(failure):
    truth, raw, membership = inputs()
    claim = raw["claims"]["synthetic-claim"]
    if failure == "human": claim["human_reviewed"] = True
    if failure == "critical": raw["fields"][0]["accepted"] = False
    if failure == "evidence": claim["required_evidence_pass"] = False
    if failure == "output": claim["output_completed"] = False
    if failure == "semantic": claim["semantic_blockers"] = ["PRINTED_DERIVED_DISAGREEMENT"]
    if failure == "field_semantic": raw["fields"][0]["semantic_blockers"] = ["SAME_UNRESOLVED"]
    if failure == "absent":
        raw["fields"][0].update(state="SOURCE_ABSENT", value=None)
        truth["records"][0].update(state="SOURCE_ABSENT", value=None)
        seal(truth, "truth_sha256")
    assert score(truth, raw, membership)["raw"]["stp_safe"] == 0


def test_zero_accepts_is_null_and_correct_automatic_requires_frozen_track_b():
    truth, raw, membership = inputs()
    assert score(truth, raw, membership)["raw"]["stp_safe"] == 1
    for row in raw["fields"]: row["accepted"] = False
    assert score(truth, raw, membership)["raw"]["accepted_precision"] is None
    truth["track"] = "TRACK_A"
    seal(truth, "truth_sha256")
    with pytest.raises(ValueError, match="TRACK_B"): score(truth, raw, membership)


def test_membership_or_policy_changes_require_new_freeze():
    truth, raw, membership = inputs()
    truth["semantic_policy_sha256"] = "old-policy"
    seal(truth, "truth_sha256")
    with pytest.raises(ValueError, match="BINDING"): score(truth, raw, membership)


def test_claim_semantic_blocker_reaches_canonical_claim_review():
    service = ClaimDecisionService.load()
    value = _context(service)
    value.semantic_blockers = ["ATTACHMENT_OWNERSHIP_UNRESOLVED"]
    result = service.decide(value)
    assert result.disposition is ClaimDisposition.CLAIM_REVIEW_REQUIRED
    assert not result.stp_eligible and not result.stp_safe
