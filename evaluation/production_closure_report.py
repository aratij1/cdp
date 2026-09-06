"""PHI-safe production-closure aggregates from measured local artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from statistics import mean, median

from evaluation.cdp2_comparison import latency_summary
from evaluation.production_latency_governor import SEMANTIC_KEYS, compare

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "evaluation_results/production_closure"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def profile_summary(profile: dict) -> dict:
    warm = [e for e in profile["experiments"] if e["mode"] == "WARM_STEADY_STATE"]
    if len(warm) < 3 or any(len(e["pages"]) != 12 for e in warm):
        raise ValueError("INCOMPLETE_QUALIFICATION")
    pages = [p for e in warm for p in e["pages"]]
    total = sum(p["stages"]["total_ms"] for p in pages)
    keys = sorted(set().union(*(p["stages"] for p in pages)))
    stages = {
        k: mean(p["stages"][k] for p in pages)
        for k in keys
        if all(isinstance(p["stages"].get(k), (int, float)) for p in pages)
    }
    native_keys = sorted(set().union(*(p["native_trace"]["elapsed_ms"] for p in pages)))
    return {
        "scope": profile["scope"],
        "threads": profile["threads"],
        "workers": profile["workers"],
        "cpu_affinity": profile["cpu_affinity"],
        "ocr_max_side": profile["ocr_max_side"],
        "cpu_memory_arena": profile["cpu_memory_arena"],
        "model_initialization_ms": profile["model_initialization_ms"],
        "cold_start_p95_ms": None,
        "cold_start_status": "ONE_START_NOT_A_DISTRIBUTION",
        "first_pass_latency": profile["experiments"][0]["latency"],
        "warm_runs": [e["latency"] for e in warm],
        "median_warm_p95_ms": median(e["latency"]["P95"] for e in warm),
        "median_warm_ocr_p95_ms": median(
            latency_summary([p["stages"]["ocr_ms"] for p in e["pages"]])["P95"] for e in warm
        ),
        "median_warm_recognizer_p95_ms": median(
            latency_summary(
                [
                    p["native_trace"]["elapsed_ms"].get("recognizer_inference_ms", 0)
                    for p in e["pages"]
                ]
            )["P95"]
            for e in warm
        ),
        "median_warm_p50_ms": median(e["latency"]["P50"] for e in warm),
        "median_warm_p99_ms": median(e["latency"]["P99"] for e in warm),
        "median_throughput_pages_per_second": median(
            e["latency"]["throughput_pages_per_second"] for e in warm
        ),
        "peak_rss_bytes": max(p["memory_rss_bytes"] for p in pages),
        "peak_working_set_bytes": max(p["peak_working_set_bytes"] or 0 for p in pages),
        "mean_process_cpu_ms_per_page": mean(p["process_cpu_ms"] for p in pages),
        "ocr_share": sum(p["stages"]["ocr_ms"] for p in pages) / total,
        "identity_share": sum(p["stages"]["identity_ms"] for p in pages) / total,
        "mean_stage_ms": stages,
        "mean_native_stage_ms_nested_in_ocr": {
            k: mean(p["native_trace"]["elapsed_ms"].get(k, 0) for p in pages) for k in native_keys
        },
        "full_page_ocr_calls_per_page": sorted({p["full_page_ocr_calls"] for p in pages}),
        "fresh_ocr_calls": sum(e["new_full_page_calls"] for e in profile["experiments"]),
        "effective_fields_per_repetition": [
            sum(p["effective_fields"] for p in e["pages"]) for e in warm
        ],
        "source_dimensions": sorted({tuple(p["dimensions"]) for p in pages}),
        "source_dpi": sorted({tuple(p["source_dpi"]) for p in pages if p["source_dpi"]}),
        "authority_lookup_latency": "NOT_MEASURABLE_WITHOUT_CONFIGURED_AUTHORITY",
        "registration_and_full_business_context": "NOT_EXECUTED_IN_THIS_SHADOW_PATH",
        "production_sla_qualified": False,
    }


def run() -> dict:
    directory = LOCAL / "latency"
    baseline = load(directory / "baseline8.local.json")
    profiles = {"baseline8": baseline}
    candidates = {}
    for name in ("two_threads", "performance_cores_isolated", "one_thread", "two_workers"):
        profile = load(directory / f"{name}.local.json")
        profiles[name] = profile
        candidates[name] = {**compare(baseline, profile), "profile": profile_summary(profile)}
    resolution = {}
    original = baseline["experiments"][0]["pages"][0]
    for size in (1800, 1600, 1400):
        p = load(directory / f"resolution_{size}.local.json")["experiments"][0]["pages"][0]
        changed = [k for k in SEMANTIC_KEYS if original[k] != p[k]]
        resolution[str(size)] = {
            "semantic_dimensions_changed": changed,
            "status": "REJECT_SEMANTIC_CHANGE" if changed else "REQUIRES_FULL_QUALIFICATION",
            "scope": "ONE_PAGE_SEMANTIC_SCREEN_NO_LATENCY_QUALIFICATION",
            "release_recall": None,
            "runtime_configuration_retained": False,
        }
    report = {
        "baseline": profile_summary(baseline),
        "candidates": candidates,
        "resolution_screens": resolution,
        "excluded_diagnostics": {
            "performance_cores": "Sequential worker isolation compromised by tracing reference cycles; replaced by isolated process run",
            "initial_trace_attempt": "DPI serialization failure; no qualified timing",
        },
        "benchmark_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.glob("*.local.json"))
        },
        "scope_limit": "Real TIFF decode, fresh OCR, strict identity and downstream shadow; not complete production claim processing or external authority SLA.",
        "production_accuracy": None,
        "production_stp": None,
        "release_status": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
    }
    selection_path = directory / "selection.json"
    if selection_path.exists():
        report["selected_configuration"] = load(selection_path)
        qualified = directory / "qualification_baseline_fallback.local.json"
        if not qualified.exists():
            qualified = directory / "qualification.local.json"
        report["fresh_qualification"] = profile_summary(load(qualified))
    out = ROOT / "docs/closure/production_latency_results.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    run()
