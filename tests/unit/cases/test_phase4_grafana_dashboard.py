import json
from pathlib import Path


def test_phase4_dashboard_covers_required_operational_views():
    path = Path("deploy/monitoring/grafana_phase4_dashboard.json")
    dashboard = json.loads(path.read_text("utf-8"))
    source = json.dumps(dashboard)
    for term in (
        "Accuracy", "STP", "Route governance", "Capacity", "Cost",
        "cdp_field_safe_coverage", "cdp_claim_stp_rate", "cdp_claim_blocker_total",
        "cdp_route_agreement_total", "cdp_queue_lag", "cdp_cost_per_document",
    ):
        assert term in source
