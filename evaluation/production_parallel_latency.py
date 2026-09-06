"""Two bounded long-lived workers, disjoint fixed pages, synchronized repetitions."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

from evaluation.cdp2_comparison import latency_summary

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/production_closure/latency"


def worker(index, barrier):
    from evaluation.closure_iteration6_latency import run

    run(
        thread_count=8,
        page_indices=tuple(range(index, 12, 2)),
        repetition_barrier=barrier,
        output_dir=OUT,
        output_name=f"parallel_worker_{index}.local.json",
    )


def run() -> dict:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    processes = [context.Process(target=worker, args=(i, barrier)) for i in range(2)]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(timeout=900)
            if process.exitcode != 0:
                raise RuntimeError("PARALLEL_WORKER_FAILED_OR_TIMED_OUT")
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
    reports = [json.loads((OUT / f"parallel_worker_{i}.local.json").read_text()) for i in range(2)]
    result = {
        **reports[0],
        "workers": 2,
        "experiments": [],
        "scope": "PARALLEL_PAGE_SERVICE_TIME_EXCLUDES_REQUEST_QUEUE_NOT_PRODUCTION_SLA",
        "session_constructions": 2,
        "model_initialization_ms": max(r["model_initialization_ms"] for r in reports),
    }
    for repetition in range(4):
        pieces = [r["experiments"][repetition] for r in reports]
        pages = [
            p for pair in zip(pieces[0]["pages"], pieces[1]["pages"], strict=True) for p in pair
        ]
        summary = latency_summary([p["stages"]["total_ms"] for p in pages])
        summary.pop("throughput_claims_per_second")
        # Each worker processes its queue sequentially; synchronized repetition
        # makes maximum worker elapsed time the conservative service makespan.
        elapsed = max(
            sum(
                p["stages"]["total_ms"] + p["stages"].get("report_io_ms_outside_page_latency", 0)
                for p in piece["pages"]
            )
            for piece in pieces
        )
        summary["throughput_pages_per_second"] = len(pages) * 1000 / elapsed
        result["experiments"].append(
            {
                **pieces[0],
                "pages": pages,
                "latency": summary,
                "new_full_page_calls": sum(piece["new_full_page_calls"] for piece in pieces),
            }
        )
    result["aggregate_peak_rss_upper_bound_bytes"] = sum(
        max(p["memory_rss_bytes"] for e in r["experiments"] for p in e["pages"]) for r in reports
    )
    (OUT / "two_workers.local.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    run()
