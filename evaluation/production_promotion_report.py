"""Machine-readable Phase 4 promotion decision; missing evidence stays missing."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from packages.production_readiness_gate import (
    ProductionReadinessGate,
    ReadinessEvidence,
)
from packages.route_registry import RouteRegistry


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation_results" / "production_readiness"


def generate_promotion_report(*, full_suite_passed: bool = False) -> dict:
    holdout = json.loads(
        (ROOT / "evaluation" / "holdout" / "manifest.json").read_text("utf-8")
    )
    evidence = ReadinessEvidence(
        holdout_frozen=holdout["freeze_status"] == "FROZEN",
        holdout_independent=False,
        holdout_documents=holdout["asset_count"],
        holdout_fields=holdout["field_observation_count"],
        full_suite_passed=full_suite_passed,
        runtime_parity_passed=True,
        route_governance_passed=True,
    )
    result = ProductionReadinessGate.load().evaluate(evidence)
    route_results = []
    for route in RouteRegistry.load().routes:
        route_results.append({
            "route_id": route.route_id,
            "field": route.field,
            "form": route.form,
            "current_status": route.status.value,
            "decision": "NEEDS_MORE_DATA",
            "new_status": route.status.value,
            "reason": (
                "NO_INDEPENDENT_HOLDOUT_OR_RUNTIME_SHADOW_EVIDENCE; "
                "current status is unchanged"
            ),
        })
    execution = [
        {"step": 1, "name": "Freeze EVIDENCE_FRONTIER_V2", "status": "COMPLETE"},
        {"step": 2, "name": "Finalize row-level claim dispositions", "status": "COMPLETE"},
        {"step": 3, "name": "Finalize claim-blocker Pareto", "status": "COMPLETE"},
        {"step": 4, "name": "Route lifecycle governance", "status": "COMPLETE"},
        {"step": 5, "name": "Runtime/evaluation parity", "status": "COMPLETE"},
        {"step": 6, "name": "Build untouched PRODUCTION_HOLDOUT_V1", "status": "NEEDS_MORE_DATA"},
        {"step": 7, "name": "Freeze holdout manifest and hashes", "status": "NOT_RUN"},
        {"step": 8, "name": "Run extraction baseline", "status": "NOT_RUN"},
        {"step": 9, "name": "Run evidence frontier", "status": "NOT_RUN"},
        {"step": 10, "name": "Synthetic-vs-holdout report", "status": "NOT_RUN_NO_HOLDOUT_METRICS"},
        {"step": 11, "name": "Evaluate routes individually", "status": "NOT_RUN"},
        {"step": 12, "name": "Promote eligible routes to SHADOW", "status": "NOT_RUN_NO_ELIGIBLE_ROUTES"},
        {"step": 13, "name": "Runtime shadow validation", "status": "NOT_RUN"},
        {"step": 14, "name": "Cost baseline", "status": "PARTIAL_SYNTHETIC_TELEMETRY_ONLY"},
        {"step": 15, "name": "1K/10K/50K load tests", "status": "NOT_RUN"},
        {"step": 16, "name": "KEDA scaling", "status": "NOT_RUN"},
        {"step": 17, "name": "Failure injection", "status": "NOT_RUN"},
        {"step": 18, "name": "Security/PHI validation", "status": "NOT_RUN"},
        {"step": 19, "name": "DB/event production gates", "status": "NOT_RUN"},
        {"step": 20, "name": "Production promotion decision", "status": "COMPLETE_FAIL_CLOSED"},
    ]
    report = {
        "report_id": "CDP_PHASE4_PRODUCTION_PROMOTION",
        "created_at": datetime.now(UTC).isoformat(),
        "decision": result.decision.value,
        "policy_version": result.policy_version,
        "gates": result.gates,
        "blocking_reasons": result.blocking_reasons,
        "evidence_status": result.evidence_status,
        "holdout_status": holdout["status"],
        "route_decisions": route_results,
        "execution_order": execution,
        "synthetic_metrics_are_production_authority": False,
        "external_ai_enabled": False,
        "next_action": (
            "Acquire and govern PRODUCTION_HOLDOUT_V1; freeze it before running "
            "EXTRACTION_BASELINE_V1 or EVIDENCE_FRONTIER_V2."
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "promotion_report.json").write_text(json.dumps(report, indent=2), "utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-suite-passed", action="store_true")
    args = parser.parse_args()
    report = generate_promotion_report(full_suite_passed=args.full_suite_passed)
    print(json.dumps({
        "decision": report["decision"],
        "holdout_status": report["holdout_status"],
        "blocking_reasons": report["blocking_reasons"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
