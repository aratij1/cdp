from packages.production_readiness_gate import (
    ProductionReadinessGate,
    ReadinessDecision,
    ReadinessEvidence,
)


def passing(**changes):
    values = {
        "holdout_frozen": True, "holdout_independent": True,
        "holdout_documents": 5000, "holdout_fields": 15000,
        "full_suite_passed": True,
        "overall_raw_accuracy": .96, "critical_accuracy": .99,
        "total_false_accept_rate": 0, "critical_false_accept_count": 0,
        "safe_field_coverage": .95, "accepted_precision": .999,
        "claim_stp": .95, "claim_hitl": .05,
        "claim_hitl_count": 250, "accepted_critical_field_decisions": 4000,
        "critical_accepted_precision": .999, "wrong_crop_recall": .97,
        "maximum_segment_claim_hitl": .10,
        "p95_latency_ms": 1000, "cost_per_document_usd": .01,
        "runtime_parity_passed": True, "route_governance_passed": True,
        "security_passed": True, "database_and_events_passed": True,
        "load_and_keda_passed": True, "shadow_validation_passed": True,
        "failure_injection_passed": True,
    }
    values.update(changes)
    return ReadinessEvidence(**values)


def test_all_gates_promote_to_production():
    result = ProductionReadinessGate.load().evaluate(passing())
    assert result.decision is ReadinessDecision.PROMOTE_TO_PRODUCTION


def test_holdout_only_can_promote_to_shadow_but_not_production():
    result = ProductionReadinessGate.load().evaluate(passing(
        security_passed=False, database_and_events_passed=False,
        load_and_keda_passed=False, shadow_validation_passed=False,
    ))
    assert result.decision is ReadinessDecision.PROMOTE_TO_SHADOW


def test_missing_holdout_needs_more_data():
    result = ProductionReadinessGate.load().evaluate(ReadinessEvidence(
        runtime_parity_passed=True, route_governance_passed=True,
    ))
    assert result.decision is ReadinessDecision.NEEDS_MORE_DATA


def test_observed_critical_false_accept_rejects():
    result = ProductionReadinessGate.load().evaluate(passing(
        critical_false_accept_count=1,
    ))
    assert result.decision is ReadinessDecision.REJECT


def test_overall_accepted_precision_is_an_independent_gate():
    result = ProductionReadinessGate.load().evaluate(passing(
        accepted_precision=.994, critical_accepted_precision=1.0,
    ))
    assert not result.gates["accepted_precision"]
    assert result.decision is ReadinessDecision.NEEDS_MORE_DATA


def test_point_estimate_cannot_bypass_confidence_bound():
    result = ProductionReadinessGate.load().evaluate(passing(
        holdout_documents=100, holdout_fields=3000, claim_hitl=.08,
        claim_hitl_count=8,
    ))
    assert not result.gates["claim_hitl_upper_confidence"]
    assert result.decision is ReadinessDecision.NEEDS_MORE_DATA


def test_measured_cost_above_ceiling_cannot_promote():
    result = ProductionReadinessGate.load().evaluate(
        passing(cost_per_document_usd=0.030001)
    )
    assert result.gates["measured_cost"]
    assert not result.gates["cost_ceiling"]
    assert result.decision is ReadinessDecision.NEEDS_MORE_DATA


def test_p95_above_five_seconds_cannot_promote():
    result = ProductionReadinessGate.load().evaluate(passing(p95_latency_ms=5000.01))
    assert not result.gates["p95_latency"]
    assert result.decision is ReadinessDecision.NEEDS_MORE_DATA
