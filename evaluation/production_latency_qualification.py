"""Select only an eligible measured configuration, then independently repeat it."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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


def qualify_target(output: Path, source_root: Path | None = None) -> dict:
    """Three isolated processes, each cold pass then fresh warm pass; no tuning."""
    output = output.resolve()
    if output == OUT.resolve():
        raise ValueError("TARGET_RUN_MUST_NOT_REPLACE_WORKSTATION_BASELINE")
    output.mkdir(parents=True, exist_ok=True)
    baseline = json.loads((OUT / "qualification.local.json").read_text())
    profiles = []
    for repetition in range(3):
        worker = output / f"target_{repetition}.local.json"
        if worker.exists():
            raise ValueError("IMMUTABLE_TARGET_OUTPUT_ALREADY_EXISTS")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "evaluation.production_latency_qualification",
                *(["--source-root", str(source_root)] if source_root is not None else []),
                "--worker-output",
                str(worker),
            ],
            check=True,
            cwd=ROOT,
            timeout=3600,
        )
        profiles.append(json.loads(worker.read_text()))
    combined = dict(profiles[0])
    combined["experiments"] = [run for profile in profiles for run in profile["experiments"]]
    decision = compare(baseline, combined, minimum_improvement=0)
    after = decision["candidate_median_warm_p95_ms"]
    decision["status"] = (
        "TARGET_HOST_MEASURED_PATH_PASS"
        if (decision["semantic_equality"] and not decision["reasons"] and after <= 5000)
        else "HOST_LATENCY_LIMIT_MEASURED"
    )
    decision["production_sla_qualified"] = False
    decision["complete_claim_path_qualification_required"] = True
    (output / "target_profile.local.json").write_text(json.dumps(combined, indent=2))
    (output / "target_qualification.json").write_text(json.dumps(decision, indent=2))
    return decision


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-output", type=Path)
    parser.add_argument("--worker-output", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    if args.worker_output:
        benchmark(
            thread_count=8,
            output_dir=args.worker_output.parent,
            output_name=args.worker_output.name,
            repetitions=2,
            source_root=args.source_root,
        )
    elif args.target_output:
        print(json.dumps(qualify_target(args.target_output, args.source_root), indent=2))
    else:
        parser.error(
            "Use --target-output for a new deployment-host qualification; historical workstation tuning is closed."
        )
