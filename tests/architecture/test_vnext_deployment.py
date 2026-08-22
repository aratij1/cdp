import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
CHART = ROOT / "deploy/helm/cdp-worker-pools"


def test_worker_pool_values_reference_real_entrypoints_and_scale_10x():
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert len(values["workers"]) >= 7
    for name, worker in values["workers"].items():
        module_path = ROOT / (worker["module"].replace(".", "/") + ".py")
        assert module_path.is_file(), f"{name} targets missing module {module_path}"
        assert worker["maxReplicas"] >= 10
        assert int(worker["lagThreshold"]) > 0


def test_worker_deployments_and_keda_targets_share_one_template():
    template = (CHART / "templates/workers.yaml").read_text(encoding="utf-8")
    assert "name: idp-{{ $name }}" in template
    assert "scaleTargetRef: {name: idp-{{ $name }}}" in template
    assert "horizontalPodAutoscalerConfig" in template
    assert "stabilizationWindowSeconds: 300" in template
    assert "fallback:" in template


def test_pods_are_restricted_and_network_is_default_deny():
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["podSecurityContext"]["runAsNonRoot"] is True
    assert values["containerSecurityContext"]["readOnlyRootFilesystem"] is True
    assert values["containerSecurityContext"]["allowPrivilegeEscalation"] is False
    assert "ALL" in values["containerSecurityContext"]["capabilities"]["drop"]
    platform = (CHART / "templates/platform.yaml").read_text(encoding="utf-8")
    assert "cdp-workers-default-deny" in platform
    assert "policyTypes: [Ingress, Egress]" in platform
    assert "automountServiceAccountToken: false" in platform


def test_vnext_dashboard_and_alert_rules_are_parseable_and_complete():
    dashboard = json.loads(
        (ROOT / "deploy/monitoring/grafana_vnext_dashboard.json").read_text(encoding="utf-8")
    )
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {"Critical false accepts", "External AI cost/hour", "Kafka consumer lag"} <= titles
    rules = yaml.safe_load((ROOT / "deploy/monitoring/alert_rules.yml").read_text(encoding="utf-8"))
    alerts = {rule["alert"] for group in rules["groups"] for rule in group["rules"]}
    assert {"CriticalFalseAcceptance", "ExternalAIBudgetBurn", "CriticalReviewBacklog"} <= alerts


def test_api_charts_have_disruption_and_non_root_controls():
    for chart in ("ingestion-api", "human-review-api"):
        root = ROOT / "deploy/helm" / chart
        values = yaml.safe_load((root / "values.yaml").read_text(encoding="utf-8"))
        assert values["podDisruptionBudget"]["enabled"] is True
        assert values["podSecurityContext"]["runAsNonRoot"] is True
        assert (root / "templates/pdb.yaml").is_file()
