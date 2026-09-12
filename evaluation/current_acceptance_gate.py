"""Publish current staged acceptance status from independently generated metrics."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    cms = json.loads(Path("evaluation_results/structured_rollout/cms1500/metrics.json").read_text())
    ub = json.loads(Path("evaluation_results/structured_rollout/ub04/metrics.json").read_text())
    attachments = json.loads(Path("evaluation_results/attachment_rollout/progress.json").read_text())
    oracle = json.loads(
        Path("evaluation_results/current_oracle_page_metrics/metrics.json").read_text()
    )
    components = [
        ("CMS1500", cms["nonblank_expected_fields"], cms["candidate_coverage"]),
        ("UB04", ub["nonblank_expected_fields"], ub["candidate_coverage"]),
        ("ATTACHMENTS", attachments["visible_source_fields"], attachments["attachment_candidate_coverage"]),
    ]
    total = sum(count for _, count, _ in components)
    matches = sum(round(count * coverage) for _, count, coverage in components)
    report = {
        "components": [
            {"name": name, "visible_fields": count, "candidate_coverage": coverage}
            for name, count, coverage in components
        ],
        "visible_fields": total,
        "candidate_matches": matches,
        "overall_candidate_coverage": matches / total,
        "overall_candidate_gate_90_met": matches / total >= 0.90,
        "critical_false_accepts": None,
        "routing_ready_completeness": None,
        "production_qualification": "NOT_EVALUABLE",
        "production_measurement_source": "evaluation.qualification_closure",
        "candidate_metrics_purpose": "ENGINEERING_DIAGNOSTIC_ONLY",
        "oracle_page_accuracy": oracle["oracle_page_accuracy"],
        "oracle_metric_status": "CURRENT_V2_PROVENANCE",
        "router_tuning_authorized": False,
    }
    output = Path("evaluation_results/current_acceptance_gate.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
