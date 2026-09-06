"""Select only an eligible measured configuration, then independently repeat it."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.closure_iteration6_latency import run as benchmark
from evaluation.production_latency_governor import compare

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/production_closure/latency"


def run() -> dict:
    baseline = json.loads((OUT / "baseline8.local.json").read_text())
    eligible = []
    for name in ("two_threads", "performance_cores_isolated", "one_thread", "two_workers"):
        profile = json.loads((OUT / f"{name}.local.json").read_text())
        decision = compare(baseline, profile)
        if decision["status"] == "KEEP_ELIGIBLE_PENDING_SAFETY":
            eligible.append((decision["candidate_median_warm_p95_ms"], name, profile))
    name, selected = "baseline8", baseline
    if eligible:
        _, name, selected = min(eligible, key=lambda item: item[0])
    if selected["workers"] != 1:
        raise ValueError("PARALLEL_WINNER_REQUIRES_SEPARATE_FRESH_QUALIFICATION")
    result = benchmark(
        thread_count=selected["threads"],
        affinity=selected["cpu_affinity"],
        output_dir=OUT,
        output_name="qualification.local.json",
    )
    comparison = compare(baseline, result)
    if name != "baseline8" and "NO_MATERIAL_P95_IMPROVEMENT" in comparison["reasons"]:
        # A selection-run win that fails to reproduce is not retained.
        name, selected = "baseline8", baseline
        result = benchmark(
            thread_count=baseline["threads"],
            affinity=baseline["cpu_affinity"],
            output_dir=OUT,
            output_name="qualification_baseline_fallback.local.json",
        )
        comparison = compare(baseline, result)
    reasons = set(comparison["reasons"]) - {"NO_MATERIAL_P95_IMPROVEMENT"}
    if reasons:
        raise ValueError("FRESH_QUALIFICATION_FAILED:" + ",".join(sorted(reasons)))
    selection = {
        "selected_experiment": name,
        "threads": selected["threads"],
        "workers": 1,
        "cpu_affinity": selected["cpu_affinity"],
        "ocr_max_side": selected["ocr_max_side"],
        "cpu_memory_arena": True,
        "fresh_qualification_semantics_equal": comparison["semantic_equality"],
        "fresh_qualification_median_warm_p95_ms": comparison["candidate_median_warm_p95_ms"],
        "production_sla_qualified": False,
        "production_configuration_activated": False,
    }
    (OUT / "selection.json").write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
    return selection


if __name__ == "__main__":
    run()
