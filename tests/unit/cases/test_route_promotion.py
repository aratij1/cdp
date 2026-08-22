from packages.production_readiness_gate import ReadinessDecision
from packages.route_registry import (
    RouteLifecycle,
    RoutePromotionEvidence,
    RoutePromotionGate,
)


def evidence(**changes):
    values = {
        "route_id": "CMS1500.patient_name.tesseract.paddleocr.v1",
        "current_status": RouteLifecycle.EVALUATION_ONLY,
        "independent_holdout_frozen": True, "holdout_samples": 100,
        "holdout_accuracy": .99, "agreement_precision": 1,
        "critical_false_agreements": 0, "mean_latency_ms": 100,
        "cost_per_call_usd": 0,
    }
    values.update(changes)
    return RoutePromotionEvidence(**values)


def test_evaluation_route_can_only_advance_to_shadow_from_holdout():
    result = RoutePromotionGate.load().evaluate(evidence())
    assert result.decision is ReadinessDecision.PROMOTE_TO_SHADOW


def test_shadow_route_requires_runtime_sample_for_production():
    gate = RoutePromotionGate.load()
    missing = gate.evaluate(evidence(current_status=RouteLifecycle.SHADOW))
    passed = gate.evaluate(evidence(
        current_status=RouteLifecycle.SHADOW,
        runtime_shadow_samples=1000, operational_reliability=1,
    ))
    assert missing.decision is ReadinessDecision.NEEDS_MORE_DATA
    assert passed.decision is ReadinessDecision.PROMOTE_TO_PRODUCTION


def test_missing_holdout_never_promotes_route():
    result = RoutePromotionGate.load().evaluate(evidence(
        independent_holdout_frozen=False, holdout_samples=0,
    ))
    assert result.decision is ReadinessDecision.NEEDS_MORE_DATA
