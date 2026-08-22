from packages.production_promotion_gate import (
    ProductionEvidence, ProductionPromotionGate, PromotionDecision,
)

def _passing(**changes):
    values = dict(
        frozen_release_integrity=True, full_suite_passed=True, unexplained_test_failures=0,
        independent_holdout_frozen=True, holdout_is_synthetic=False,
        holdout_documents=100, holdout_fields=300, overall_accuracy=.9,
        critical_accuracy=.9, critical_false_accept_rate=0, total_false_accept_rate=0,
        safe_stp_rate=.6, load_test_passed=True, kubernetes_keda_test_passed=True,
        disaster_recovery_test_passed=True, security_assessment_passed=True,
    )
    values.update(changes)
    return ProductionEvidence(**values)

def test_all_evidence_gates_can_promote():
    result = ProductionPromotionGate.load().evaluate(_passing())
    assert result.decision is PromotionDecision.PROMOTABLE
    assert all(result.gates.values())

def test_synthetic_data_can_never_satisfy_independent_holdout_gate():
    result = ProductionPromotionGate.load().evaluate(_passing(holdout_is_synthetic=True))
    assert result.decision is PromotionDecision.BLOCKED
    assert not result.gates["independent_non_synthetic_holdout"]

def test_missing_metrics_and_known_failure_block_fail_closed():
    result = ProductionPromotionGate.load().evaluate(ProductionEvidence(unexplained_test_failures=1))
    assert result.decision is PromotionDecision.BLOCKED
    assert "ZERO_UNEXPLAINED_TEST_FAILURES" in result.blocking_reasons
    assert "CRITICAL_ACCURACY" in result.blocking_reasons
