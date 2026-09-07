"""Integrity checks reject incomplete lineage without disclosing field observations."""

import copy
import json

import pytest

from packages.real_data_evaluation.blind_workflow import FIELDS
from packages.real_data_evaluation.real_release_integrity import (
    claim_binding_report,
    review_checkpoint_integrity,
)


def fixture():
    digest = "b" * 64
    membership = {
        "governed": True,
        "complete_claim_membership_confirmed": True,
        "boundary_provenance": "governed-test",
        "claims": {
            "sensitive-claim": {
                "package_id": "sensitive-package",
                "page_ids": ["p"],
                "claim_form_page_ids": ["p"],
                "attachment_page_ids": [],
                "documents": {
                    "d": {
                        "page_ids": ["p"],
                        "boundary": "CONFIRMED",
                        "boundary_provenance": "human-governed",
                    }
                },
                "expected_field_keys": [["p", f] for f in FIELDS],
            }
        },
    }
    bindings = [
        {
            "source_page_id": "p",
            "cdp_page_id": "runtime-p",
            "state": "EXACT",
            "rendered_page_sha256": digest,
            "cdp_page_sha256": digest,
            "package_id": "sensitive-package",
        }
    ]
    records = [
        {
            "page_id": "p",
            "field_name": f,
            "source_sha256": digest,
            "package_id": "sensitive-package",
            "value": "SENSITIVE",
        }
        for f in FIELDS
    ]
    return membership, bindings, {"records": records}, {"fields": copy.deepcopy(records)}


def test_binding_is_aggregate_and_complete():
    report = claim_binding_report(*fixture())
    assert report["status"] == "PASS"
    assert report["claims_exactly_bound"] == 1
    assert report["claim_binding_coverage"] == 1
    assert "sensitive" not in json.dumps(report).lower()


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (
            lambda m, b, t, p: m.pop("complete_claim_membership_confirmed"),
            "GOVERNED_COMPLETE_MEMBERSHIP_REQUIRED",
        ),
        (
            lambda m, b, t, p: m["claims"]["sensitive-claim"].pop("documents"),
            "CONFIRMED_DOCUMENT_BOUNDARIES_REQUIRED",
        ),
        (
            lambda m, b, t, p: m["claims"]["sensitive-claim"].pop("attachment_page_ids"),
            "COMPLETE_FORM_AND_ATTACHMENT_SCOPE_REQUIRED",
        ),
        (lambda m, b, t, p: t["records"].pop(), "COMPLETE_TRUTH_FIELDS_REQUIRED"),
        (lambda m, b, t, p: p["fields"].pop(), "COMPLETE_PREDICTION_FIELDS_REQUIRED"),
        (
            lambda m, b, t, p: p["fields"][0].update(source_sha256="wrong"),
            "EXACT_PREDICTION_BINDING_REQUIRED",
        ),
        (lambda m, b, t, p: b.append(copy.deepcopy(b[0])), "AMBIGUOUS_SOURCE_BINDING"),
    ],
)
def test_binding_refuses_incomplete_or_ambiguous_inputs(mutation, reason):
    args = fixture()
    mutation(*args)
    report = claim_binding_report(*args)
    assert report["status"] == "NOT_EVALUABLE"
    assert report["claims_exactly_bound"] == 0
    assert report["claims_excluded"] == 1
    assert report["exclusion_reasons"][reason] == 1


def test_shared_page_excludes_both_claims():
    args = fixture()
    args[0]["claims"]["second"] = copy.deepcopy(args[0]["claims"]["sensitive-claim"])
    report = claim_binding_report(*args)
    assert report["claims_ambiguous"] == report["claims_excluded"] == 2


def test_no_membership_is_not_evaluable_not_zero_coverage():
    report = claim_binding_report({}, [], {}, {})
    assert report["status"] == "NOT_EVALUABLE"
    assert report["claim_binding_coverage"] is None


def review_fixture(count):
    annotation = {
        "fields": {
            f: {"state": "VALUE", "value": "SENSITIVE", "region": [0, 0, 1, 1]} for f in FIELDS
        },
        "form": "CMS1500",
        "quality": "GOOD",
        "boundary": "START_CLAIM",
        "prediction_visible": False,
    }
    sources = {str(n): {"rendered_page_sha256": "b" * 64} for n in range(150)}
    rows = [
        {
            "page_id": str(n),
            "reviewer_id": "a",
            "source_sha256": "b" * 64,
            "annotation": copy.deepcopy(annotation),
        }
        for n in range(count)
    ]
    registry = {
        "identity_verified": True,
        "policy_id": "governed-test",
        "authorized_reviewers": ["a", "b"],
        "adjudicators": ["c"],
    }
    return {"pages_total": 150, "pages_reviewed": count}, rows, sources, registry


@pytest.mark.parametrize("count", [0, 10, 25, 50, 100, 150])
def test_checkpoints_only_release_workflow_integrity(count):
    report = review_checkpoint_integrity(
        *review_fixture(count),
        machinery={
            "comparison_logic": True,
            "denominators": True,
            "qualification_machinery": True,
        },
    )
    assert report["status"] == "PASS"
    assert report["milestones_reached"] == [n for n in (10, 25, 50, 100, 150) if n <= count]
    assert report["interim_production_metrics_released"] is False
    assert "SENSITIVE" not in json.dumps(report)


def test_missing_self_checks_remain_pending():
    report = review_checkpoint_integrity(*review_fixture(10))
    assert report["status"] == "PENDING"
    assert "COMPARISON_LOGIC_NOT_VALIDATED" in report["pending"]


def test_checkpoint_detects_unregistered_reviews_and_denominator_inflation():
    args = review_fixture(10)
    args[1][0]["reviewer_id"] = "unregistered"
    report = review_checkpoint_integrity(*args)
    assert report["status"] == "FAIL"
    assert report["issues"]["REVIEW_PROVENANCE_INVALID"] == 1
    assert report["issues"]["REVIEW_DENOMINATOR_MISMATCH"] == 1


def test_checkpoint_detects_nonindependent_adjudication():
    args = review_fixture(10)
    report = review_checkpoint_integrity(
        *args,
        adjudications=[
            {
                "page_id": "0",
                "field_name": FIELDS[0],
                "adjudicator_id": "a",
                "review_digest": "forged",
            }
        ],
    )
    assert report["issues"]["ADJUDICATION_PROVENANCE_INVALID"] == 1


def execution_fixture():
    from packages.real_data_evaluation.blind_workflow import content_digest

    membership, bindings, truth, prediction = fixture()
    truth["status"] = "FROZEN"
    truth["truth_sha256"] = content_digest(truth)
    candidate = {"candidate_commit_sha": "a" * 40}
    prediction.update(
        candidate_commit_sha=candidate["candidate_commit_sha"],
        scope="CANONICAL_PRODUCTION_PIPELINE",
        purpose="FINAL_GATE",
        used_for_tuning=False,
        execution_provenance=["test"],
        claims={
            "sensitive-claim": {
                "validation_complete": True,
                "required_evidence_pass": True,
                "authority_complete": True,
                "decision_complete": True,
                "output_completed": True,
            }
        },
    )
    prediction["snapshot_sha256"] = content_digest(prediction)
    return membership, bindings, truth, prediction, candidate


def test_execution_manifest_redacts_ids_preserves_declared_sequence():
    from packages.real_data_evaluation.real_release_integrity import claim_execution_manifest

    result = claim_execution_manifest(*execution_fixture())
    assert result["execution_complete"] == 1
    assert result["claims"][0]["execution_status"] == "ELIGIBLE"
    assert result["claims"][0]["raw_scoring_ready"] is True
    assert "sensitive" not in json.dumps(result).lower()
    assert result["claims"][0]["page_ids"] == result["claims"][0]["page_sequence"]


def test_incomplete_final_output_does_not_exclude_raw_hitl_claim():
    from packages.real_data_evaluation.blind_workflow import content_digest
    from packages.real_data_evaluation.real_release_integrity import claim_execution_manifest

    membership, bindings, truth, snapshot, candidate = execution_fixture()
    snapshot["claims"]["sensitive-claim"].update(output_completed=False, authority_complete=False)
    snapshot["snapshot_sha256"] = content_digest(
        {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    )
    result = claim_execution_manifest(membership, bindings, truth, snapshot, candidate)
    assert result["claims"][0]["execution_status"] == "INCOMPLETE_EXECUTION"
    assert result["claims"][0]["raw_scoring_ready"] is True
    assert result["excluded"] == 0
    assert result["claims"][0]["execution_started"] is True
    assert result["claims"][0]["execution_complete"] is False
    assert result["claims"][0]["output_status"] == "PENDING"


def test_missing_membership_truth_and_execution_are_not_guessed():
    from packages.real_data_evaluation.real_release_integrity import claim_execution_manifest

    assert claim_execution_manifest({}, [], {}, {}, {})["claims"] == []
    membership, bindings, truth, snapshot, candidate = execution_fixture()
    assert (
        claim_execution_manifest(membership, bindings, {}, snapshot, candidate)["claims"][0][
            "execution_status"
        ]
        == "INCOMPLETE_TRUTH"
    )
    membership["claims"]["sensitive-claim"].pop("documents")
    assert (
        claim_execution_manifest(membership, bindings, truth, snapshot, candidate)["claims"][0][
            "execution_status"
        ]
        == "INCOMPLETE_MEMBERSHIP"
    )


def test_tampered_execution_seal_cannot_claim_completion():
    from packages.real_data_evaluation.real_release_integrity import claim_execution_manifest

    membership, bindings, truth, snapshot, candidate = execution_fixture()
    snapshot["claims"]["sensitive-claim"]["output_completed"] = False
    result = claim_execution_manifest(membership, bindings, truth, snapshot, candidate)
    assert result["execution_complete"] == 0
    assert result["claims"][0]["prediction_complete"] is False
    assert result["claims"][0]["output_complete"] is None
