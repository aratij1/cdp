"""Configurable measured-machine and canonical-HITL Phase 8.2 cost model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def run(results: Path, performance: Path, config_path: Path) -> dict:
    config = yaml.safe_load(config_path.read_text("utf-8"))
    perf = json.loads(performance.read_text("utf-8"))
    hitl = json.loads((results / "hitl_metrics.json").read_text("utf-8"))
    stp = json.loads((results / "stp_metrics.json").read_text("utf-8"))
    pages = perf["pages"]
    wall_per_page = perf["wall_seconds"] / pages
    cpu_per_page = perf["cpu_seconds"] / pages
    memory_gb = perf["memory_peak_gb"]
    cpu_cost = cpu_per_page * config["cpu_cost_per_core_hour_usd"] / 3600
    memory_cost = memory_gb * wall_per_page * config["memory_cost_per_gb_hour_usd"] / 3600
    machine_page = cpu_cost + memory_cost
    pages_per_document = float(config["pages_per_document"])
    machine = {
        "cost_model_version": config["version"],
        "rate_scenario": config["scenario_label"],
        "measured_worker_count": perf["worker_count"],
        "cpu_seconds": perf["cpu_seconds"], "wall_seconds": perf["wall_seconds"],
        "memory_peak_gb": memory_gb,
        "full_page_ocr_calls": perf["full_page_ocr_calls_per_page"] * pages,
        "regional_ocr_calls": perf["regional_ocr_calls_per_page"] * pages,
        "cpu_seconds_per_page": cpu_per_page,
        "cpu_cost_per_core_hour_usd": config["cpu_cost_per_core_hour_usd"],
        "memory_cost_per_gb_hour_usd": config["memory_cost_per_gb_hour_usd"],
        "machine_compute_cost_per_page_usd": machine_page,
        "machine_cost_per_document_usd": machine_page * pages_per_document,
        "machine_cost_per_1000_pages_usd": machine_page * 1000,
        "machine_cost_per_1m_pages_usd": machine_page * 1_000_000,
    }
    field_cost = (
        config["reviewer_hourly_cost_usd"] * config["average_field_review_seconds"] / 3600
    )
    field_review_page = hitl["review_fields_per_page"] * field_cost
    overhead_claim = (
        config["reviewer_hourly_cost_usd"] *
        config["claim_open_close_overhead_seconds"] / 3600
    )
    overhead_page = overhead_claim * hitl["claim_hitl_rate"] / pages_per_document
    hitl_page = field_review_page + overhead_page
    scenarios = []
    eligible_fields_per_page = hitl["eligible_fields"] / 100
    for rate in config["scenario_field_hitl_rates"]:
        for seconds in config["scenario_review_seconds"]:
            scenarios.append({
                "label": "SCENARIO ONLY", "field_hitl_rate": rate,
                "review_seconds_per_field": seconds,
                "field_review_cost_per_page_usd": (
                    eligible_fields_per_page * rate *
                    config["reviewer_hourly_cost_usd"] * seconds / 3600
                ),
            })
    hitl_cost = {
        "cost_model_version": config["version"],
        "rate_scenario": config["scenario_label"],
        "measured_field_hitl_rate": hitl["field_hitl_rate"],
        "measured_claim_hitl_rate": hitl["claim_hitl_rate"],
        "reviewer_hourly_cost_usd": config["reviewer_hourly_cost_usd"],
        "average_field_review_seconds": config["average_field_review_seconds"],
        "claim_open_close_overhead_seconds": config["claim_open_close_overhead_seconds"],
        "review_cost_per_field_usd": field_cost,
        "field_review_cost_per_page_usd": field_review_page,
        "claim_overhead_cost_per_page_usd": overhead_page,
        "hitl_cost_per_page_usd": hitl_page,
        "hitl_cost_per_document_usd": hitl_page * pages_per_document,
        "hitl_cost_per_reviewed_claim_usd": hitl_page * pages_per_document,
        "scenarios": scenarios,
    }
    shared = config["shared_infra_cost_per_page_usd"]
    cloud = config["cloud_ai_cost_per_page_usd"]
    total_page = machine_page + hitl_page + shared + cloud
    stp_claims = stp["stp_claims"]
    reviewed_claims = stp["claims"] - stp_claims
    fully_loaded = {
        "cost_model_version": config["version"],
        "rate_scenario": config["scenario_label"],
        "machine_processing_cost_per_page_usd": machine_page,
        "cloud_ai_cost_per_page_usd": cloud,
        "hitl_cost_per_page_usd": hitl_page,
        "shared_infra_cost_per_page_usd": shared,
        "total_cost_per_page_usd": total_page,
        "total_cost_per_document_usd": total_page * pages_per_document,
        "cost_per_stp_claim_usd": (
            total_page * pages_per_document if stp_claims else None
        ),
        "cost_per_reviewed_claim_usd": (
            total_page * pages_per_document if reviewed_claims else None
        ),
        "cost_per_1000_pages_usd": total_page * 1000,
        "cost_per_1m_pages_usd": total_page * 1_000_000,
        "future_exception_route_equation": (
            "consider only when expected_safe_review_cost_avoided > "
            "expected_extra_machine_or_ai_cost and safety_policy_permits"
        ),
    }
    for name, payload in (
        ("machine_cost.json", machine), ("hitl_cost.json", hitl_cost),
        ("fully_loaded_cost.json", fully_loaded),
    ):
        (results / name).write_text(json.dumps(payload, indent=2), "utf-8")
    return {"machine": machine, "hitl": hitl_cost, "fully_loaded": fully_loaded}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=ROOT / "evaluation_results/phase8_2")
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "config/phase8_2_cost_model.yaml")
    args = parser.parse_args()
    print(json.dumps(run(args.results, args.performance, args.config), indent=2))
