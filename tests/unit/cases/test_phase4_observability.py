from packages.observability import metrics


REQUIRED = {
    "cdp_raw_accuracy", "cdp_critical_accuracy", "cdp_field_safe_coverage", "cdp_field_hitl_rate", "cdp_claim_stp_rate",
    "cdp_claim_hitl_rate", "cdp_false_accept_total",
    "cdp_critical_false_accept_total", "cdp_route_invocation_total",
    "cdp_route_shadow_total", "cdp_route_agreement_total",
    "cdp_route_false_agreement_total", "cdp_policy_decision_total",
    "cdp_claim_blocker_total", "cdp_cost_per_document",
    "cdp_cost_per_stp_claim", "cdp_queue_lag", "cdp_p95_document_latency",
    "cdp_cost_per_review_avoided",
}


def test_phase4_metrics_exist_and_have_phi_safe_labels():
    forbidden = {"value", "candidate", "patient", "member_id", "claim_id", "document_id"}
    for name in REQUIRED:
        collector = getattr(metrics, name)
        assert forbidden.isdisjoint(collector._labelnames)
