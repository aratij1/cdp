from packages.production_readiness_gate import (
    ProductionReadinessGate,
    ReadinessDecision,
    ReadinessEvidence,
)


def passing(**changes):
    values = {
        "holdout_frozen": True, "holdout_independent": True,
        "holdout_documents": 200, "holdout_fields": 1000,
        "full_suite_passed": True,
        "overall_raw_accuracy": .96, "critical_accuracy": .99,
        "total_false_accept_rate": 0, "critical_false_accept_count": 0,
        "safe_field_coverage": .80, "claim_stp": .75, "claim_hitl": .25,
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
