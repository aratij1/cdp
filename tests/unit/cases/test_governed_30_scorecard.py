"""Engineering metrics never borrow blind cohort denominators."""

from copy import deepcopy

import pytest

from evaluation.governed_30_scorecard import score


def fixture():
    manifest = {
        "cohort_hash": "synthetic",
        "claims": [
            {"claim_alias": "C1", "source_hash": "source1"},
            {"claim_alias": "C2", "source_hash": "source2"},
        ],
    }
    references = {
        "cohort_hash": "synthetic",
        "authority": "ENGINEERING_REFERENCE_ONLY",
        "claims": [
            {
                "claim_alias": name,
                "form_type": "CMS1500",
                "fields": {"member_id": {"status": "REFERENCE_AVAILABLE", "value": "SYNTHETIC"}},
            }
            for name in ("C1", "C2")
        ],
    }
    claims = []
    for i, name in enumerate(("C1", "C2"), 1):
        field = {
            "field_id": name,
            "field_name": "member_id",
            "raw_value": "SYNTHETIC",
            "service_line_number": None,
            "validation_status": "VALID",
            "disposition": "AUTO_ACCEPTED",
            "extraction_method": "OCR",
        }
        decision = {
            "field_id": name,
            "disposition": "AUTO_ACCEPTED",
            "next_action": "NONE",
            "available_evidence": ["synthetic_only"],
        }
        claims.append(
            {
                "claim_alias": name,
                "source_sha256": f"source{i}",
                "execution_complete": True,
                "fields": [field],
                "events": [{"envelope": {"payload": {"field_decisions": [decision]}}}],
                "tasks": [],
                "claim_decision": {"disposition": "STP_SAFE", "stp_eligible": True},
                "output_completed": True,
                "actual_human_intervention": False,
            }
        )
    execution = {
        "cohort_hash": "synthetic",
        "scope": "GOVERNED_ENGINEERING",
        "reference_values_used_for_inference": False,
        "actual_human_reviews": 0,
        "claims": claims,
    }
    return manifest, references, execution


def test_complete_execution_measures_all_eligible_claims():
    result, failures = score(*fixture())
    assert result["raw_accuracy"] == {
        "numerator": 2,
        "denominator": 2,
        "percentage": 100,
        "status": "MEASURED",
    }
    assert result["true_stp"]["numerator"] == 2
    assert result["field_hitl"]["numerator"] == 0
    assert result["accepted_precision"]["numerator"] == 2
    assert not failures["failures"]


def test_missing_candidate_counts_wrong_without_invented_field_route():
    manifest, references, execution = fixture()
    execution["claims"][0]["fields"] = []
    result, failures = score(manifest, references, execution)
    assert result["raw_accuracy"]["numerator"] == 1
    assert result["raw_accuracy"]["denominator"] == 2
    assert result["field_hitl"]["status"] == "NOT_EVALUABLE"
    assert result["field_hitl"]["denominator"] == 2
    assert failures["failures"][0]["category"] == "CANDIDATE_MISSING"


def test_missing_field_blocker_is_observed_review_routing():
    manifest, references, execution = fixture()
    claim = execution["claims"][0]
    claim["fields"] = []
    claim["claim_decision"] = {
        "disposition": "FIELD_REVIEW_REQUIRED",
        "blocking_unresolved_fields": ["member_id"],
    }
    result, _ = score(manifest, references, execution)
    assert result["field_hitl"]["numerator"] == 1
    assert result["claim_hitl"]["numerator"] == 1
    assert result["true_stp"]["numerator"] == 1


def test_conflicting_page_candidates_do_not_cherry_pick_matching_value():
    manifest, references, execution = fixture()
    rows = execution["claims"][0]["fields"]
    rows.append({**deepcopy(rows[0]), "field_id": "OTHER", "raw_value": "DIFFERENT"})
    result, failures = score(manifest, references, execution)
    assert result["raw_accuracy"]["numerator"] == 1
    assert failures["failures"][0]["candidate_occurrences"] == 2


def test_incomplete_execution_cannot_claim_zero_hitl_or_raw_accuracy():
    manifest, references, execution = fixture()
    execution["claims"][0]["execution_complete"] = False
    result, _ = score(manifest, references, execution)
    execution["claims"][0]["claim_decision"] = {}
    result, _ = score(manifest, references, execution)
    for name in ("raw_accuracy", "claim_hitl", "true_stp", "field_hitl"):
        assert result[name]["numerator"] is None
        assert result[name]["denominator"] == 2
        assert result[name]["status"] == "NOT_EVALUABLE"


def test_human_reference_injection_never_counts_as_auto_acceptance():
    manifest, references, execution = fixture()
    execution["claims"][0]["fields"][0]["disposition"] = "HUMAN_CONFIRMED"
    execution["claims"][0]["actual_human_intervention"] = True
    result, _ = score(manifest, references, execution)
    assert result["accepted_precision"]["denominator"] == 1
    assert result["true_stp"]["numerator"] == 1
    assert result["field_hitl"]["numerator"] == 1


def test_safe_decision_without_output_does_not_count_as_stp():
    manifest, references, execution = fixture()
    execution["claims"][0]["output_completed"] = False
    result, _ = score(manifest, references, execution)
    assert result["true_stp"]["numerator"] == 1
    assert result["true_stp"]["denominator"] == 2


def test_acceptance_requires_recorded_evidence_and_uses_effective_value():
    manifest, references, execution = fixture()
    execution["claims"][0]["fields"][0]["normalized_value"] = "WRONG"
    result, _ = score(manifest, references, execution)
    assert result["raw_accuracy"]["numerator"] == 2
    assert result["accepted_precision"]["numerator"] == 1
    execution["claims"][0]["events"] = []
    result, _ = score(manifest, references, execution)
    assert result["accepted_precision"]["denominator"] == 1


@pytest.mark.parametrize("change", ["cohort", "source", "duplicate", "injected"])
def test_input_isolation_fails_closed(change):
    manifest, references, execution = fixture()
    if change == "cohort":
        execution["cohort_hash"] = "blind"
    elif change == "source":
        execution["claims"][0]["source_sha256"] = "blind-source"
    elif change == "duplicate":
        execution["claims"].append(execution["claims"][0])
    else:
        execution["reference_values_used_for_inference"] = True
    with pytest.raises(ValueError):
        score(manifest, references, execution)


def test_output_failure_does_not_hide_completed_extraction_and_routing():
    manifest, references, execution = fixture()
    failed = execution["claims"][0]
    failed["execution_complete"] = False
    failed["output_completed"] = False
    failed["failures"] = [{"topic": "claim.validated", "error_type": "ValueError"}]
    failed["events"].extend([{"topic": "extraction.completed"}, {"topic": "claim.validated"}])
    result, _ = score(manifest, references, execution)
    assert result["raw_accuracy"]["numerator"] == 2
    assert result["critical_accuracy"]["status"] == "MEASURED"
    assert result["accepted_precision"]["status"] == "MEASURED"
    assert result["claim_hitl"]["denominator"] == 2
    assert result["claim_hitl"]["status"] == "MEASURED"
    assert result["true_stp"]["numerator"] == 1
    assert result["status"] == "MEASURED_WITH_EXECUTION_FAILURES"


@pytest.mark.parametrize("terminal", [False, True])
def test_canonical_empty_extraction_or_terminal_no_route_stays_in_denominator(terminal):
    manifest, references, execution = fixture()
    claim = execution["claims"][0]
    claim.update(
        fields=[],
        claim_decision={},
        execution_complete=False,
        output_completed=False,
        document_status="NEEDS_REVIEW",
    )
    claim["events"] = (
        [
            {
                "topic": "page.selected",
                "envelope": {
                    "payload": {
                        "needs_review": True,
                        "reason_codes": ["NO_AUTOMATED_EXTRACTION_ROUTE"],
                    }
                },
            }
        ]
        if terminal
        else [{"topic": "extraction.completed"}]
    )
    result, _ = score(manifest, references, execution)
    assert result["raw_accuracy"]["numerator"] == 1
    assert result["raw_accuracy"]["denominator"] == 2
    assert result["claim_hitl"]["numerator"] == 1
    assert result["true_stp"]["numerator"] == 1
    assert result["field_hitl"]["status"] == "NOT_EVALUABLE"
    assert result["field_hitl_bounds"]["unknown_routing"] == 1
    assert result["field_hitl_bounds"]["upper_numerator"] == 1


def test_unspecified_review_state_does_not_prove_extraction_attempt():
    manifest, references, execution = fixture()
    execution["claims"][0].update(
        execution_complete=False, events=[], document_status="NEEDS_REVIEW"
    )
    result, _ = score(manifest, references, execution)
    assert result["raw_accuracy"]["status"] == "NOT_EVALUABLE"
