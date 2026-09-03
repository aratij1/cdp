"""Measured uncached Phase 8.11 worker-scaling benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from evaluation.phase8_1_golden import run
from evaluation.phase8_8_generalization import DATA_ROOT, SOURCE_IDS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation_results/phase8_11/throughput"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _selected_documents(pages: int) -> list[tuple[str, dict]]:
    documents: list[tuple[str, dict]] = []
    manifests = {
        source: json.loads((DATA_ROOT / source / "manifest.json").read_text("utf-8"))
        for source in SOURCE_IDS
    }
    by_source_family = {
        (source, family): [
            item for item in manifests[source]["documents"]
            if item["family"].startswith(family)
        ]
        for source in SOURCE_IDS
        for family in ("CMS", "UB")
    }
    index = 0
    while len(documents) < pages:
        progressed = False
        for family in ("CMS", "UB"):
            for source in SOURCE_IDS:
                items = by_source_family[(source, family)]
                if index < len(items) and len(documents) < pages:
                    documents.append((source, items[index]))
                    progressed = True
        if not progressed:
            break
        index += 1
    return documents


def _make_shard(root: Path, shard_id: int, items: list[tuple[str, dict]]) -> Path:
    shard = root / f"shard-{shard_id}"
    shard.mkdir(parents=True)
    documents = []
    ids = {item["document_id"] for _, item in items}
    fields: list[dict[str, str]] = []
    lines: list[dict[str, str]] = []
    field_columns: list[str] = []
    line_columns: list[str] = []
    for source, item in items:
        source_root = DATA_ROOT / source
        target_file = Path(source) / item["file"]
        (shard / target_file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / item["file"], shard / target_file)
        documents.append({**item, "file": target_file.as_posix()})
    for source in sorted({source for source, _ in items}):
        source_root = DATA_ROOT / source
        source_fields = _read_csv(source_root / "field_truth.csv")
        field_columns = field_columns or list(source_fields[0])
        fields.extend(row for row in source_fields if row["document_id"] in ids)
        source_lines = _read_csv(source_root / "ub04_service_line_truth.csv")
        line_columns = line_columns or list(source_lines[0])
        lines.extend(row for row in source_lines if row["document_id"] in ids)
    manifest = {
        "dataset_id": f"PHASE8_11_THROUGHPUT_SHARD_{shard_id}",
        "dataset_role": "BENCHMARK",
        "synthetic": True,
        "contains_real_phi": False,
        "engineering_only": True,
        "production_authority": False,
        "document_count": len(documents),
        "field_truth_rows": len(fields),
        "ub_service_line_rows": len(lines),
        "documents": documents,
    }
    (shard / "manifest.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    _write_csv(shard / "field_truth.csv", fields, field_columns)
    _write_csv(shard / "ub04_service_line_truth.csv", lines, line_columns)
    return shard


def _profile(workers: int, pages: int, temp: Path, output: Path) -> dict:
    selected = _selected_documents(pages)
    buckets = [[] for _ in range(workers)]
    for index, item in enumerate(selected):
        buckets[index % workers].append(item)
    shards = [_make_shard(temp / f"workers-{workers}", index, bucket)
              for index, bucket in enumerate(buckets) if bucket]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(run, shard, output / f"workers-{workers}/shard-{index}",
                        run_id="uncached", reuse_observations=False)
            for index, shard in enumerate(shards)
        ]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - started
    processed = sum(item["documents"] for item in results)
    return {
        "workers": workers, "pages": processed, "wall_seconds": elapsed,
        "pages_per_second": processed / elapsed,
        "documents_per_minute": processed / elapsed * 60,
        "benchmark_mode": True, "prior_document_output_cache": "DISABLED",
        "cloud_calls": sum(item["cloud_calls"] for item in results),
        "false_accepts": sum(item["false_accepts"] for item in results),
        "stage_latency_ms": [item.get("stage_latency_ms", {}) for item in results],
    }


def run_benchmark(
    output: Path = OUTPUT,
    pages: int = 12,
    worker_profiles: tuple[int, ...] = (1, 2, 4, 8),
) -> dict:
    os.environ["BENCHMARK_MODE"] = "true"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cdp-phase811-") as directory:
        profiles = []
        for workers in worker_profiles:
            profiles.append(_profile(workers, pages, Path(directory), output))
            (output / "partial.json").write_text(
                json.dumps({"profiles": profiles}, indent=2) + "\n", "utf-8"
            )
    best = max(profiles, key=lambda item: item["pages_per_second"])
    result = {
        "phase": "8.11", "pages_per_profile": pages, "profiles": profiles,
        "best_worker_count": best["workers"],
        "best_pages_per_second": best["pages_per_second"],
        "latency_is_not_used_as_throughput": True,
        "locked_holdout_accessed": False,
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=12)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--profiles", default="1,2,4,8")
    args = parser.parse_args()
    profiles = tuple(int(item) for item in args.profiles.split(",") if item.strip())
    print(json.dumps(run_benchmark(args.output, args.pages, profiles), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
