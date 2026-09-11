"""Docker-free OCR benchmark orchestration.

No Kafka, database, object store, or API is required. Inference modules call
the same extraction/reconciliation services used by workers.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument(
        "--predictions", type=Path,
        default=Path("evaluation_data/predictions_family_cascade.json"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evaluation_results/offline_benchmark")
    )
    parser.add_argument(
        "--run-inference", action="store_true",
        help="Rebuild crops and execute local OCR; requires OCR dependencies.",
    )
    parser.add_argument(
        "--dataset", type=Path, default=Path("dataset_raw"),
        help="Source dataset root forwarded to build_field_crops and "
        "run_unstructured_family_cascade (which both default to dataset_raw).",
    )
    parser.add_argument("--split", choices=["calibration", "validation", "holdout"])
    args = parser.parse_args()
    if args.run_inference:
        _run("-m", "evaluation.build_field_crops", "--dataset", str(args.dataset))
        _run(
            "-m", "evaluation.inventory_unstructured",
            "--dataset", str(args.dataset / "Group D"),
        )
        _run("-m", "evaluation.run_atomic_ocr")
        _run("-m", "evaluation.run_handwriting_cascade")
        _run(
            "-m", "evaluation.run_unstructured_family_cascade",
            "--dataset", str(args.dataset),
        )
    runner = [
        "-m", "evaluation.runner",
        "--ground-truth", str(args.ground_truth),
        "--predictions", str(args.predictions),
        "--output", str(args.output),
    ]
    if args.split:
        runner.extend(["--split", args.split])
    _run(*runner)
    _run(
        "-m", "evaluation.comparison_report",
        "--ground-truth", str(args.ground_truth),
        "--predictions", str(args.predictions),
        "--assets", "evaluation_results/field_crops",
        "--output", str(args.output / "comparison.html"),
    )
    _run(
        "-m", "evaluation.error_backlog",
        "--ground-truth", str(args.ground_truth),
        "--predictions", str(args.predictions),
        "--output", str(args.output / "error_backlog"),
    )
    # Publish the latest governed router/reconciliation view at the stable URL.
    _run("-m", "evaluation.current_comparison_report")
    print(f"Offline benchmark complete: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
