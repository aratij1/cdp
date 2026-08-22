"""Static preflight for load tiers and deployable Kafka/KEDA worker pools."""
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path
import yaml

REQUIRED_TIERS = {1_000, 10_000, 50_000}
REQUIRED_METRICS = {"pages_per_second", "documents_per_hour", "p50_latency_ms",
    "p95_latency_ms", "p99_latency_ms", "cpu_utilization", "memory_bytes",
    "kafka_lag", "database_connections", "postgres_transactions_per_second",
    "redis_hit_ratio", "object_store_bytes_per_second", "ai_calls", "review_rate", "cost_usd"}

def validate(root: Path) -> dict:
    load = yaml.safe_load((root / "config/load_test_tiers.yaml").read_text("utf-8"))
    values = yaml.safe_load((root / "deploy/helm/cdp-worker-pools/values.yaml").read_text("utf-8"))
    tiers = {int(item["pages"]) for item in load["tiers"]}; metrics = set(load["required_metrics"])
    errors: list[str] = []
    if tiers != REQUIRED_TIERS: errors.append(f"load tiers must be {sorted(REQUIRED_TIERS)}")
    if missing := REQUIRED_METRICS - metrics: errors.append(f"missing metrics: {sorted(missing)}")
    workers = values.get("workers", {})
    for name, worker in workers.items():
        module = worker.get("module", "")
        if not module or importlib.util.find_spec(module) is None:
            errors.append(f"worker {name} has no importable entrypoint: {module}")
        if int(worker.get("maxReplicas", 0)) < int(worker.get("minReplicas", 0)):
            errors.append(f"worker {name} has maxReplicas below minReplicas")
        if not worker.get("topic") or not worker.get("lagThreshold"):
            errors.append(f"worker {name} lacks Kafka scaling metadata")
    return {"status": "PASS" if not errors else "FAIL", "load_tiers": sorted(tiers),
        "required_metrics": sorted(metrics), "worker_pools": sorted(workers),
        "errors": errors, "cluster_load_test_executed": False}

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(".")); parser.add_argument("--output", type=Path)
    args = parser.parse_args(); report = validate(args.root.resolve()); encoded = json.dumps(report, indent=2)
    if args.output: args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(encoded + "\n", "utf-8")
    print(encoded); return 0 if report["status"] == "PASS" else 2

if __name__ == "__main__": raise SystemExit(main())
