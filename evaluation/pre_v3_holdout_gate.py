"""Fail-closed development gates that must pass before a V3 holdout is created."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.templates import TemplateRegistry
from packages.templates.registry import DEFAULT_TEMPLATE_DIR
from workers.standard_form_extraction.extractor import REGION_COALESCE_TOLERANCE_PX


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTING = ROOT / "evaluation_results/ROUTING_DEV_V2/benchmark.json"
DEFAULT_EXTRACTION = ROOT / "evaluation_results/raw_accuracy_recovery/final/baseline/metrics.json"
DEFAULT_OUTPUT = ROOT / "evaluation_results/PRE_V3_DEVELOPMENT_GATE/report.json"


def _equivalent(left, right) -> bool:
    a = (left.x0, left.y0, left.x1, left.y1)
    b = (right.x0, right.y0, right.x1, right.y1)
    return all(abs(x-y) <= REGION_COALESCE_TOLERANCE_PX for x, y in zip(a, b))


def _regional_cost() -> dict:
    registry = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    forms = {}
    for template_id, version in (("cms1500", "02-12"), ("ub04", "2014")):
        template = registry.get(template_id, version)
        representatives = []
        for region in template.field_regions:
            if not any(_equivalent(region, prior) for prior in representatives):
                representatives.append(region)
        logical, executed = len(template.field_regions), len(representatives)
        forms[template.form_type.value] = {
            "logical_regional_requests": logical,
            "executed_regional_requests": executed,
            "coalesced_requests": logical-executed,
            "request_reduction_rate": (logical-executed)/logical,
        }
    return forms


def evaluate(routing_path: Path = DEFAULT_ROUTING,
             extraction_path: Path = DEFAULT_EXTRACTION) -> dict:
    routing = json.loads(routing_path.read_text("utf-8"))
    extraction = json.loads(extraction_path.read_text("utf-8"))
    ub = routing["metrics"]["UB04"]
    overall = extraction["overall"]["accuracy"]
    false_accepts = extraction.get("qualification", {}).get("false_accepts")
    cost = _regional_cost()
    checks = {
        "independent_development_ub04_recall_at_least_98pct": ub["recall"] >= .98,
        "independent_development_ub04_precision_100pct": ub["precision"] == 1.0,
        "development_standard_extraction_accuracy_at_least_99pct": overall >= .99,
        "development_false_accepts_zero": false_accepts == 0,
        "regional_ocr_requests_reduced_for_all_standard_forms": all(
            item["coalesced_requests"] > 0 for item in cost.values()
        ),
    }
    return {
        "status": "READY_TO_CREATE_FRESH_V3_HOLDOUT" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "metrics": {
            "ub04_recall": ub["recall"], "ub04_precision": ub["precision"],
            "standard_extraction_accuracy": overall, "false_accepts": false_accepts,
            "regional_ocr_cost": cost,
        },
        "governance": {
            "routing_source": str(routing_path),
            "extraction_source": str(extraction_path),
            "holdout_used_for_tuning": False,
            "v3_holdout_created": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routing", type=Path, default=DEFAULT_ROUTING)
    parser.add_argument("--extraction", type=Path, default=DEFAULT_EXTRACTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = evaluate(args.routing, args.extraction)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"].startswith("READY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
