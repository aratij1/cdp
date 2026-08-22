"""Auditable processing + infrastructure + HITL cost-per-page scenarios."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import yaml

def calculate(config: dict) -> dict:
    processing = config["processing"]
    route_cost = sum(float(item["share"]) * float(item["unit_cost_usd"])
                     for item in processing["route_mix"].values())
    pages_per_second = float(processing["local_ocr_fields_per_second"]) / float(processing["assumed_ocr_fields_per_page"])
    compute_cost = (float(processing["local_ocr_concurrency"]) * float(processing["assumed_vcpu_cost_per_hour_usd"])) / (pages_per_second * 3600)
    platform_cost = float(processing["storage_orchestration_per_page_usd"])
    pre_hitl = route_cost + compute_cost + platform_cost
    review_unit = float(config["hitl"]["cost_per_reviewed_page_usd"])
    scenarios = {}
    for name, rate_value in config["scenarios"].items():
        rate = float(rate_value)
        hitl_cost = rate * review_unit
        scenarios[name] = {
            "review_rate": rate, "processing_route_cost_per_page_usd": route_cost,
            "compute_cost_per_page_usd": compute_cost,
            "storage_orchestration_per_page_usd": platform_cost,
            "pre_hitl_cost_per_page_usd": pre_hitl,
            "hitl_cost_per_page_usd": hitl_cost,
            "total_cost_per_page_usd": pre_hitl + hitl_cost,
            "hitl_share_of_total": hitl_cost / (pre_hitl + hitl_cost),
        }
    return {"version": config["version"], "currency": config["currency"],
            "status": "PROJECTED_FROM_MEASURED_THROUGHPUT_AND_CONFIGURED_UNIT_COSTS",
            "scenarios": scenarios,
            "caveats": ["Reviewer unit cost is configured, not payroll-measured",
                        "vCPU and platform unit costs are planning assumptions",
                        "route mix is illustrative until production telemetry exists"]}

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--config",type=Path,default=Path("config/cost_model_v1.yaml")); parser.add_argument("--output",type=Path,default=Path("evaluation_results/cost_model_v1/report.json")); args=parser.parse_args()
    report=calculate(yaml.safe_load(args.config.read_text("utf-8")))
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,indent=2),"utf-8")
    print(json.dumps(report,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
