"""Synthetic contract tests only; fixtures are never release evidence."""

import copy

import pytest

from packages.real_data_evaluation.blind_workflow import content_digest
from packages.real_data_evaluation.release_scoring import score_release


def seal(value, key):
    value[key] = content_digest({k: v for k, v in value.items() if k != key})
    return value


def inputs():
    names = ["patient_name", "patient_dob", "total_charge", "principal_diagnosis"]
    values = ["DOE, JANE", "2000-01-02", "$1,200.00", "E11.9"]
    truth = seal(
        {
            "status": "FROZEN",
            "records": [
                {
                    "page_id": "synthetic-page",
                    "package_id": "synthetic-package",
                    "field_name": name,
                    "critical": i < 2,
                    "authority": "DUAL_REVIEW_AGREED",
                    "state": "VALUE",
                    "value": values[i],
                }
                for i, name in enumerate(names)
            ],
        },
        "truth_sha256",
    )
    membership = {
        "governed": True,
        "boundary_provenance": "synthetic-test",
        "claims": {
            "synthetic-claim": {
                "page_ids": ["synthetic-page"],
                "package_id": "synthetic-package",
                "expected_field_keys": [["synthetic-page", name] for name in names],
            }
        },
    }
    raw = {
        "scope": "CANONICAL_PRODUCTION_PIPELINE",
        "used_for_tuning": False,
        "purpose": "FINAL_GATE",
        "configuration_sha256": "c" * 64,
        "execution_provenance": ["synthetic-test"],
        "fields": [
            {
                "page_id": r["page_id"],
                "field_name": r["field_name"],
                "state": "VALUE",
                "value": r["value"],
                "accepted": True,
                "review_required": False,
            }
            for r in truth["records"]
        ],
        "claims": {
            "synthetic-claim": {
                "decision": "STP_SAFE",
                "human_corrected": False,
                "human_reviewed": False,
                "required_fields_pass": True,
                "required_evidence_pass": True,
                "output_completed": True,
                "automatic_output_safely_generated": True,
            }
        },
    }
    return truth, raw, membership


def score(truth, raw, membership, final=None):
    return score_release(
        truth,
        seal(raw, "snapshot_sha256"),
        seal(final, "snapshot_sha256") if final is not None else None,
        membership,
    )


def test_governed_comparisons_and_integer_denominators():
    truth, raw, membership = inputs()
    for row, value in zip(raw["fields"], ["DOE JANE", "01/02/2000", "1200", "E119"], strict=True):
        row["value"] = value
    metrics = score(truth, raw, membership)["raw"]
    assert metrics["accuracy"] == 1
    assert (metrics["accuracy_numerator"], metrics["accuracy_denominator"]) == (4, 4)
    assert metrics["critical_accuracy_numerator"] == 2
    assert metrics["noncritical_accuracy_denominator"] == 2
    assert metrics["stp_numerator"] == metrics["stp_denominator"] == 1


def test_review_and_human_fields_are_never_automatic_accepts():
    truth, raw, membership = inputs()
    raw["fields"][0].update(value="WRONG", review_required=True)
    raw["fields"][1].update(value="WRONG", human_corrected=True)
    result = score(truth, raw, membership)
    metrics = result["raw"]
    assert metrics["accepted_precision_denominator"] == 2
    assert metrics["critical_accepted_precision"] is None
    assert metrics["critical_false_accepts"] == 0
    assert metrics["field_hitl_numerator"] == 2
    assert metrics["hitl_ownership"] == {"UNKNOWN": 2}
    assert metrics["claim_hitl_numerator"] == 1 and metrics["stp_numerator"] == 0
    assert result["error_analysis"] == {"UNCLASSIFIED": 2}


def test_true_false_accept_survives_final_correction():
    truth, raw, membership = inputs()
    final = copy.deepcopy(raw)
    raw["fields"][0]["value"] = "WRONG"
    final["claims"]["synthetic-claim"].update(human_corrected=True, revalidation_completed=True)
    result = score(truth, raw, membership, final)
    assert result["raw"]["critical_false_accepts"] == 1
    assert result["post_hitl"]["final_accuracy"] == 1
    assert result["post_hitl"]["hitl_closed_claims"] == 1
    assert result["post_hitl"]["true_stp_claims"] == 0


@pytest.mark.parametrize(
    "flag", ["output_completed", "required_fields_pass", "required_evidence_pass", "human_reviewed"]
)
def test_stp_requires_complete_positive_evidence(flag):
    truth, raw, membership = inputs()
    del raw["claims"]["synthetic-claim"][flag]
    result = score(truth, raw, membership)["raw"]
    assert result["stp_numerator"] == 0
    assert (
        result["stp_claims"] + result["hitl_claims"] + result["unresolved_claims"]
        == result["eligible_claims"]
    )


def test_revalidated_claim_without_output_is_unresolved():
    truth, raw, membership = inputs()
    final = copy.deepcopy(raw)
    raw["fields"][0]["review_required"] = True
    final["claims"]["synthetic-claim"].update(
        human_corrected=True, revalidation_completed=True, output_completed=False
    )
    result = score(truth, raw, membership, final)["post_hitl"]
    assert result["hitl_closed_claims"] == 0
    assert result["unresolved"] == 1
    assert result["claims_successfully_revalidated"] == 1


def test_reason_classification_requires_observed_evidence():
    truth, raw, membership = inputs()
    raw["fields"][0].update(
        value="WRONG",
        review_required=True,
        hitl_owner="SOURCE_REVIEW",
        error_classification="WRONG_RANK",
    )
    result = score(truth, raw, membership)
    assert result["error_analysis"] == {"UNCLASSIFIED": 1}
    assert result["raw"]["claim_blocker_combinations"] == {"SOURCE_REVIEW": 1}
    raw["fields"][0]["error_evidence"] = "synthetic-evidence-ref"
    assert score(truth, raw, membership)["error_analysis"] == {"WRONG_RANK": 1}
