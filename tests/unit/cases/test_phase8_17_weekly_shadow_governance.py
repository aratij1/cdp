from evaluation.phase8_17_weekly_shadow_governance import generate_weekly_governance
from packages.production_readiness_gate import ReadinessEvidence
from packages.shadow_evaluation import AppendOnlyShadowClaimSink, ClaimShadowObservation


def observation(index: int) -> ClaimShadowObservation:
    return ClaimShadowObservation(
        claim_id=f"claim-{index}", source_group_id=f"source-{index}",
        source_segment="CMS1500_SCANNER_A", production_requires_review=True,
        shadow_requires_review=index < 50, evaluated_field_decisions=10,
        correct_field_decisions=10, evaluated_critical_field_decisions=3,
        correct_critical_field_decisions=3, accepted_field_decisions=10,
        accepted_critical_field_decisions=3, correct_accepted_field_decisions=10,
        correct_accepted_critical_field_decisions=3, false_accepts=0,
        critical_false_accepts=0, wrong_crops=1, wrong_crops_detected=1,
        runtime_latency_ms=100, cost_usd=.01, runtime_decision_parity=True,
        route_governance_passed=True,
    )


def operational_evidence() -> ReadinessEvidence:
    return ReadinessEvidence(
        full_suite_passed=True, security_passed=True,
        database_and_events_passed=True, load_and_keda_passed=True,
        failure_injection_passed=True,
    )


def test_weekly_artifact_is_hash_addressed_and_non_authoritative(tmp_path):
    ledger = tmp_path / "shadow.jsonl"
    sink = AppendOnlyShadowClaimSink(ledger, identity_key=b"secret")
    for index in range(1000):
        sink.append(observation(index))
    first = generate_weekly_governance(
        ledger, as_of_week="2026-W36", base_evidence=operational_evidence()
    )
    second = generate_weekly_governance(
        ledger, as_of_week="2026-W36", base_evidence=operational_evidence()
    )
    assert first.exit_code == 0
    assert first.artifact["artifact_sha256"] == second.artifact["artifact_sha256"]
    assert first.artifact["promotion_authority"] is False
    assert first.artifact["shadow_qualification"]["claim_hitl"] == .05
    assert first.artifact["production_readiness"]["decision"] == "PROMOTE_TO_PRODUCTION"


def test_insufficient_week_fails_closed(tmp_path):
    ledger = tmp_path / "shadow.jsonl"
    AppendOnlyShadowClaimSink(ledger, identity_key=b"secret").append(observation(1))
    result = generate_weekly_governance(ledger, as_of_week="2026-W36")
    assert result.exit_code == 2
    assert result.artifact["shadow_qualification"]["status"] == "NEEDS_MORE_DATA"
    assert result.artifact["production_readiness"]["decision"] == "NEEDS_MORE_DATA"
