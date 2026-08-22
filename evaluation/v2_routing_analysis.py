"""Routing confusion and Pareto analysis for the frozen rejected baseline."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.audit_production_holdout_v2 import DEFAULT_DATASET


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation_results/production_holdout_v2"
OUTPUT = ROOT / "evaluation_results/PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED"
TRUTH = {
    "CMS1500_0212": "CMS1500", "UB04_CMS1450_COMPAT": "UB04",
    "CUSTOM_PROFESSIONAL_CLAIM": "UNKNOWN_STRUCTURED",
    "CLAIM_ATTACHMENT": "UNKNOWN_UNSTRUCTURED", "NON_CLAIM": "NON_CLAIM",
}
ROUTES = ("CMS1500", "UB04", "UNKNOWN_STRUCTURED", "UNKNOWN_UNSTRUCTURED", "NON_CLAIM")


def analyze() -> dict:
    predictions = {item["document_id"]: item for item in
                   json.loads((RESULTS / "predictions.json").read_text("utf-8"))}
    truth = {item["document_id"]: item for item in
             (json.loads(line) for line in (DEFAULT_DATASET / "ground_truth/ground_truth.jsonl").read_text("utf-8").splitlines())
             if item["document_id"] in predictions}
    matrix = defaultdict(Counter)
    for document_id, expected in truth.items():
        matrix[expected["family"]][predictions[document_id]["route"]] += 1
    per_route = {}
    for route in ROUTES:
        tp = sum(count for family, row in matrix.items() for predicted, count in row.items()
                 if TRUTH[family] == route and predicted == route)
        fp = sum(count for family, row in matrix.items() for predicted, count in row.items()
                 if TRUTH[family] != route and predicted == route)
        fn = sum(count for family, row in matrix.items() for predicted, count in row.items()
                 if TRUTH[family] == route and predicted != route)
        precision = tp/(tp+fp) if tp+fp else None; recall = tp/(tp+fn) if tp+fn else None
        per_route[route] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision,
                            "recall": recall,
                            "f1": 2*precision*recall/(precision+recall) if precision and recall else 0}
    total = len(predictions)
    false_standard = sum(count for family, row in matrix.items() for route, count in row.items()
                         if route in {"CMS1500", "UB04"} and TRUTH[family] != route)
    report = {
        "documents": total,
        "matrix": {family: {route: row.get(route, 0) for route in ROUTES}
                   for family, row in matrix.items()},
        "per_route": per_route,
        "false_standard_form_routing_rate": false_standard/total,
        "unknown_fallback_rate": sum(row.get("UNKNOWN_STRUCTURED",0)+row.get("UNKNOWN_UNSTRUCTURED",0)
                                     for row in matrix.values())/total,
        "pareto": sorted((
            {"truth_family": family, "predicted_route": route, "count": count}
            for family, row in matrix.items() for route, count in row.items()
            if route != TRUTH[family]
        ), key=lambda item: item["count"], reverse=True),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "routing_analysis.json").write_text(json.dumps(report, indent=2), "utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(analyze(), indent=2))
