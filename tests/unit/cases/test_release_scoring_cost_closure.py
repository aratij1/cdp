"""Synthetic contract checks; these never create production truth or prices."""

from decimal import Decimal

import pytest

from packages.real_data_evaluation.blind_workflow import content_digest
from packages.real_data_evaluation.qualification_cost import Rates, Workload, calculate
from tests.unit.cases.test_qualification_closure_inputs import snapshots


def seal(snapshot):
    snapshot["snapshot_sha256"] = content_digest(
        {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    )


def test_duplicate_expected_fields_are_not_a_complete_denominator():
    truth, raw, final, membership, score = snapshots()
    keys = membership["claims"]["claim"]["expected_field_keys"]
    keys.append(keys[0])
    with pytest.raises(ValueError, match="DENOMINATOR"):
        score(truth, raw, final, membership)


@pytest.mark.parametrize("flag", ["accepted", "review_required"])
def test_non_boolean_field_flags_fail_closed(flag):
    truth, raw, final, membership, score = snapshots()
    raw["fields"][0][flag] = "false"
    seal(raw)
    with pytest.raises(ValueError, match="BOOLEAN_EXECUTION_FLAGS_REQUIRED"):
        score(truth, raw, final, membership)


@pytest.mark.parametrize("flag", ["review_required", "human_corrected", "human_reviewed"])
def test_claim_level_human_work_counts_as_hitl(flag):
    truth, raw, _, membership, score = snapshots()
    for field in raw["fields"]:
        field["review_required"] = False
    raw["claims"]["claim"][flag] = True
    seal(raw)
    result = score(truth, raw, None, membership)
    assert result["raw"]["claim_hitl"] == 1
    assert result["raw"]["stp"] == 0
    assert result["post_hitl"] == {}
    for dimension in result["breakdowns"].values():
        for group in dimension.values():
            assert group["claim_hitl"] == 1
            assert group["stp"] == 0


def test_pending_final_review_cannot_be_counted_as_closed():
    truth, raw, final, membership, score = snapshots()
    final["fields"][0]["review_required"] = True
    seal(final)
    result = score(truth, raw, final, membership)["post_hitl"]
    assert result["claims_successfully_closed"] == 0
    assert result["unresolved"] == 1


def test_final_human_review_without_correction_is_not_true_stp():
    truth, raw, final, membership, score = snapshots()
    for field in raw["fields"]:
        field["review_required"] = False
    final["claims"]["claim"]["human_corrected"] = False
    final["claims"]["claim"]["human_reviewed"] = True
    seal(raw)
    seal(final)
    result = score(truth, raw, final, membership)["post_hitl"]
    assert result["true_stp_claims"] == 0
    assert result["hitl_closed_claims"] == 1
    assert result["unresolved"] == 0


def test_cost_components_sum_without_double_charging_ocr_runtime():
    work = Workload(100, 10, Decimal(100), Decimal("0.5"), True, 10, 1000, 100, 20)
    rates = Rates(
        Decimal(1),
        Decimal(2),
        Decimal(".001"),
        Decimal(1),
        Decimal(2),
        Decimal(".01"),
        Decimal(".001"),
    )
    result = calculate(work, rates)
    components = result["components"]
    assert Decimal(components["cpu_runtime"]["cost_per_page"]) == Decimal(".02")
    assert Decimal(components["gpu_runtime"]["cost_per_page"]) == Decimal(".04")
    assert sum(Decimal(row["cost_per_page"]) for row in components.values()) == Decimal(
        result["total_cost_per_page"]
    )
    assert "INCLUDED_IN_FULL_PATH" in result["ocr_runtime_allocation"]


def test_unknown_cost_components_stay_unknown_while_unused_gpu_is_zero():
    result = calculate(Workload(100, 0), Rates())
    assert result["components"]["cpu_runtime"]["status"] == "NOT_CONFIGURED"
    assert result["components"]["gpu_runtime"]["cost_per_page"] == "0"
    assert result["total_cost_per_page"] is None
    with pytest.raises(ValueError, match="BOOLEAN_GPU_USAGE_REQUIRED"):
        calculate(Workload(100, 0, gpu_used="false"), Rates())


@pytest.mark.parametrize("decision", ["FIELD_REVIEW_REQUIRED", "CLAIM_REVIEW_REQUIRED"])
def test_canonical_claim_review_disposition_counts_without_field_review(decision):
    truth, raw, _, membership, score = snapshots()
    for field in raw["fields"]:
        field["review_required"] = False
    raw["claims"]["claim"]["decision"] = decision
    seal(raw)
    result = score(truth, raw, None, membership)
    assert result["raw"]["field_hitl"] == 0
    assert result["raw"]["claim_hitl"] == 1
    assert result["raw"]["stp"] == 0
