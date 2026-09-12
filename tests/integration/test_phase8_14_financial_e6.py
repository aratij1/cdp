from evaluation.phase8_10b_total_charge_e6 import run
from tests.integration.test_phase8_10b_total_charge_e6 import frozen_inputs


def test_reconciled_totals_still_require_document_and_membership_authority():
    result = run(
        write_outputs=False,
        candidate_financial_authority=True,
        **frozen_inputs(),
    )
    assert result["decision"] == "REVERT"
    assert result["correct_but_reviewed_reduction"] == 0
    assert result["treatment"]["total_charge"]["accepted_correct"] == 0
    assert result["treatment"]["total_charge"]["false_accepts"] == 0
    assert result["treatment"]["critical_false_accepts"] == 0
    assert result["non_total_charge_decision_changes"] == []

    assert result["treatment"]["total_charge"]["reason_codes"]["AUTHORITY_FORM_IDENTITY_REQUIRED"] > 0
    assert result["treatment"]["total_charge"]["reason_codes"]["AUTHORITY_MEMBERSHIP_REQUIRED"] > 0
