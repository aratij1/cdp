from evaluation.phase8_10b_total_charge_e6 import run


def test_evaluation_financial_authority_unlocks_only_reconciled_correct_totals():
    result = run(write_outputs=False, candidate_financial_authority=True)
    assert result["decision"] == "PROMOTE"
    assert result["correct_but_reviewed_reduction"] == 24
    assert result["treatment"]["total_charge"]["accepted_correct"] == 24
    assert result["treatment"]["total_charge"]["false_accepts"] == 0
    assert result["treatment"]["critical_false_accepts"] == 0
    assert result["non_total_charge_decision_changes"] == []
