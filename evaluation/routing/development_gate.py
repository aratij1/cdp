"""Worst-source Phase 7A.10 development gate. It cannot create a candidate."""
from __future__ import annotations

import json
from pathlib import Path


GATES = {
    "top_level_worst_recall": (">=", .95),
    "standard_precision": (">=", .99),
    "standard_recall": (">=", .95),
    "cms1500_nomination_recall": (">=", .98),
    "ub04_nomination_recall": (">=", .98),
    "processing_route_accuracy": (">=", .98),
    "false_standard_authorization_rate": ("<=", .005),
    "unverified_fixed_authorization_count": ("<=", 0),
    "route_extractor_firewall_violations": ("<=", 0),
}


def evaluate_gate(loso_report: dict) -> dict:
    checks = {}
    aggregate = loso_report.get("aggregate", {})
    for metric, (operator, threshold) in GATES.items():
        value = aggregate.get(metric, {}).get("worst_source")
        passed = value is not None and (value >= threshold if operator == ">=" else value <= threshold)
        checks[metric] = {"value": value, "operator": operator, "threshold": threshold, "passed": passed}
    passed = bool(loso_report.get("source_metrics")) and all(item["passed"] for item in checks.values())
    return {"gate": "PHASE_7A_12_DEVELOPMENT", "basis": "WORST_SOURCE", "checks": checks,
            "passed": passed, "decision": "PASS" if passed else "NEEDS_MORE_DATA",
            "candidate_creation_allowed": passed, "frozen_abcd_allowed": passed}


def main(input_path: str, output_path: str) -> None:
    report = json.loads(Path(input_path).read_text("utf-8"))
    Path(output_path).write_text(json.dumps(evaluate_gate(report), indent=2), "utf-8")
