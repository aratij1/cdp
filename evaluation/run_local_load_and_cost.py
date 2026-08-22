"""Concurrent local OCR load test with explicit cost-governance accounting."""

from __future__ import annotations

import argparse
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import monotonic

from PIL import Image

from workers.cascade.tesseract_adapter import for_field_type


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(int((len(ordered) - 1) * fraction), len(ordered) - 1)]


def _recognize(path: Path) -> tuple[float, bool]:
    started = monotonic()
    try:
        with Image.open(path) as image:
            for_field_type("text").extract(image.convert("RGB"))
        return (monotonic() - started) * 1000, True
    except Exception:
        return (monotonic() - started) * 1000, False


def _profile(paths: list[Path], concurrency: int) -> dict:
    started = monotonic(); latencies = []; successes = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_recognize, path) for path in paths]
        for future in as_completed(futures):
            latency, success = future.result(); latencies.append(latency); successes += int(success)
    elapsed = monotonic() - started
    return {
        "concurrency": concurrency, "requests": len(paths), "successes": successes,
        "errors": len(paths) - successes, "wall_seconds": elapsed,
        "fields_per_second": len(paths) / elapsed,
        "p50_latency_ms": _percentile(latencies, .50),
        "p95_latency_ms": _percentile(latencies, .95),
        "p99_latency_ms": _percentile(latencies, .99),
        "mean_latency_ms": statistics.mean(latencies),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evaluation_data/synthetic_public_v1/crops"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/local_load_cost_v1/report.json"))
    parser.add_argument("--requests", type=int, default=240)
    args = parser.parse_args()
    paths = sorted(args.dataset.glob("**/*.png"))[:args.requests]
    if len(paths) < args.requests:
        raise ValueError(f"requested {args.requests} crops but only found {len(paths)}")
    profiles = [_profile(paths, concurrency) for concurrency in (1, 4)]
    target = profiles[-1]
    component_pass = (target["fields_per_second"] >= 2.9 and target["p95_latency_ms"] <= 2000
                      and target["errors"] / target["requests"] <= .01)
    report = {
        "version": "local-load-cost-v1", "scope": "LOCAL_FIELD_OCR_COMPONENT",
        "dataset": "synthetic_public_v1", "profiles": profiles,
        "service_target_basis": "50000 pages/day x assumed 5 OCR fields/page",
        "component_gate_passed": component_pass,
        "full_pipeline_load_test_passed": False,
        "cost_governance": {
            "tesseract_calls": sum(profile["requests"] for profile in profiles),
            "rapidocr_calls": 0, "paddleocr_calls": 0, "docling_calls": 0,
            "gemini_calls": 0, "textract_calls": 0, "human_reviews": 0,
            "metered_provider_cost_usd": 0.0,
            "local_cpu_cost_usd": None, "storage_cost_usd": None,
            "cost_per_document_usd": None,
            "note": "Local execution has no provider charge; infrastructure cost requires deployment telemetry.",
        },
        "limitations": ["No Kafka/database/object-store path", "No Kubernetes/KEDA autoscaling",
                        "No cloud-provider calls", "No soak or dependency-failure injection"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report, indent=2))
    return 0 if component_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
