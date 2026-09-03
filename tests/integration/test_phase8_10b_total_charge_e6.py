from evaluation.phase8_10b_total_charge_e6 import run
from packages.claim_evidence import ClaimEvidenceBuilder


def _types(items):
    return {item.evidence_type for item in items}


def test_claim_total_builder_emits_the_policy_eligible_e6_name_only_on_reconciliation():
    builder = ClaimEvidenceBuilder.load()
    matched = builder.build(
        claim_id="matched",
        document_family="UB04",
        claim_values={"total_charge": "30.00"},
        service_lines=[{"charges": "20.00"}, {"charges": "10.00"}],
    )
    assert "CLAIM_TOTAL_CONFIRMED" in _types(matched.evidence_items)
    assert "CLAIM_TOTAL_RECONCILED" not in _types(matched.evidence_items)

    mismatched = builder.build(
        claim_id="mismatched",
        document_family="UB04",
        claim_values={"total_charge": "31.00"},
        service_lines=[{"charges": "20.00"}, {"charges": "10.00"}],
    )
    assert "CLAIM_TOTAL_CONFIRMED" not in _types(mismatched.evidence_items)
    assert "CLAIM_TOTAL_CONTRADICTION" in _types(mismatched.contradictions)


def test_frozen_replay_does_not_bypass_calibration_with_total_charge_e6():
    result = run(write_outputs=False)
    assert result["decision"] == "REVERT"
    assert result["correct_but_reviewed_reduction"] == 0
    assert result["treatment"]["total_charge"]["accepted_correct"] == 0
    assert result["treatment"]["total_charge"]["false_accepts"] == 0
    assert result["non_total_charge_decision_changes"] == []
    assert result["treatment"]["critical_false_accepts"] == result["baseline"][
        "critical_false_accepts"
    ]
    assert result["policy_changed"] is False
    assert result["ocr_changed"] is False
    assert result["localization_changed"] is False
    assert result["ub_reconstruction_changed"] is False
