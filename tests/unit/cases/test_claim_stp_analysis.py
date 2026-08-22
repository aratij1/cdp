import json
from pathlib import Path

from evaluation.claim_stp_analysis import analyze, claim_unlock_value


ROOT = Path(__file__).resolve().parents[3]


def test_canonical_claim_frontier_meets_target_without_false_accepts():
    payload = json.loads((
        ROOT / "evaluation_results" / "evidence_optimization" /
        "optimized" / "dispositions.json"
    ).read_text(encoding="utf-8"))
    claims, metrics, blockers, blocker_sets = analyze(payload["rows"])
    assert len(claims) == 120
    assert metrics["claim_stp_rate"] == .8
    assert metrics["claim_hitl_rate"] == .2
    assert metrics["false_accepts"] == 0
    assert metrics["target_claim_stp_over_70_percent"]
    assert metrics["target_claim_hitl_under_30_percent"]
    assert blockers
    assert blocker_sets


def test_claim_unlock_value_does_not_credit_multi_blocker_claims():
    rows = [
        {"blocking_unresolved_fields": ["patient_name"]},
        {"blocking_unresolved_fields": ["patient_name", "patient_dob"]},
        {"blocking_unresolved_fields": []},
    ]
    value = claim_unlock_value(rows, "patient_name", "HUMAN_REVIEW")
    assert value["claims_blocked"] == 2
    assert value["potential_claims_unlocked"] == 1
    assert value["potential_stp_gain"] == 1 / 3
