"""Uncached canonical Phase-8.2 throughput and stage profiler."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from packages.document_taxonomy.taxonomy import DocumentClass
from packages.extraction_geometry import FormIdentityDecision, FormIdentityStatus
from packages.page_observation import PageObservationService
from packages.templates.registry import TemplateRegistry
from workers.page_detection.text_extraction import (
    RapidOCRFullPageTextExtractor, RapidOCRTextExtractor,
)
from workers.standard_form_extraction import (
    StandardFormExtractionService, StandardFormProcessingService,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation_data/phase8_1_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V1"
_LOCAL = threading.local()


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


class _TimedExtractor:
    def __init__(self, inner):
        self.inner = inner
        self.full_calls = 0
        self.regional_calls = 0
        self.full_ms = 0.0
        self.regional_ms = 0.0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def extract(self, image):
        started = time.perf_counter()
        try:
            return self.inner.extract(image)
        finally:
            self.full_calls += 1
            self.full_ms += (time.perf_counter() - started) * 1000

    def extract_region(self, image, x0, y0, x1, y1):
        started = time.perf_counter()
        try:
            return self.inner.extract_region(image, x0, y0, x1, y1)
        finally:
            self.regional_calls += 1
            self.regional_ms += (time.perf_counter() - started) * 1000


def _initialize_worker() -> None:
    full_inner = RapidOCRFullPageTextExtractor()
    regional_inner = RapidOCRTextExtractor()
    # Warm model/session once per process-equivalent worker, but do not warm
    # page or crop result caches. Every benchmark page remains an OCR miss.
    full_inner._load()
    regional_inner._load()
    full = _TimedExtractor(full_inner)
    regional = _TimedExtractor(regional_inner)
    extraction = StandardFormExtractionService(regional)
    _LOCAL.context = {
        "full": full,
        "regional": regional,
        "processor": StandardFormProcessingService(
            PageObservationService(full, preprocessing_version="document-preparation-v1"),
            extraction,
        ),
        "templates": TemplateRegistry.load_from_directory(),
        "initializations": full_inner.initialization_count + regional_inner.initialization_count,
    }


def _ready(barrier: threading.Barrier) -> None:
    barrier.wait()


def _process(doc: dict, dataset: Path, submitted_at: float) -> dict:
    context = _LOCAL.context
    task_started = time.perf_counter()
    decode_started = time.perf_counter()
    with Image.open(dataset / doc["file"]) as source:
        image = source.convert("RGB")
    decode_ms = (time.perf_counter() - decode_started) * 1000
    family = "CMS1500" if doc["family"].startswith("CMS") else "UB04"
    template = (
        context["templates"].get("cms1500", "02-12")
        if family == "CMS1500" else context["templates"].get("ub04", "2014")
    )
    identity = FormIdentityDecision(
        family=DocumentClass.CMS1500 if family == "CMS1500" else DocumentClass.UB04,
        status=FormIdentityStatus.VERIFIED, score=1,
    )
    before_full_ms, before_regional_ms = context["full"].full_ms, context["regional"].regional_ms
    before_full_calls = context["full"].full_calls
    before_regional_calls = context["regional"].regional_calls
    processing = context["processor"].process(
        image, template, 1, identity, page_id=doc["document_id"],
        page_sha256=doc["sha256"],
    )
    serialization_started = time.perf_counter()
    processing.model_dump_json()
    serialization_ms = (time.perf_counter() - serialization_started) * 1000
    full_ms = context["full"].full_ms - before_full_ms
    regional_ms = context["regional"].regional_ms - before_regional_ms
    raw_stages = dict(processing.diagnostics.stage_ms)
    page_observation_ms = raw_stages.pop("page_observation", 0.0)
    stages = {
        **raw_stages,
        "image_open_decode": decode_ms,
        "full_page_rapidocr": full_ms,
        "page_observation_non_ocr": max(0.0, page_observation_ms - full_ms),
        # Detail-only: already contained by field-candidate and UB stages.
        "regional_rapidocr_detail": regional_ms,
        "serialization_output": serialization_ms,
    }
    return {
        "document_id": doc["document_id"], "family": family,
        "queue_wait_ms": (task_started - submitted_at) * 1000,
        "processing_ms": (time.perf_counter() - task_started) * 1000,
        "stage_ms": stages,
        "full_page_ocr_calls": context["full"].full_calls - before_full_calls,
        "regional_ocr_calls": context["regional"].regional_calls - before_regional_calls,
        "engine_initializations_worker": context["initializations"],
    }


def run(dataset: Path, output: Path, workers: int) -> dict:
    manifest = json.loads((dataset / "manifest.json").read_text("utf-8"))
    documents = manifest["documents"]
    memory_peak = 0
    stop = threading.Event()
    try:
        import psutil
        process = psutil.Process()
        def sample_memory():
            nonlocal memory_peak
            while not stop.wait(.1):
                memory_peak = max(memory_peak, process.memory_info().rss)
    except ImportError:
        def sample_memory():
            return None
    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    with ThreadPoolExecutor(max_workers=workers, initializer=_initialize_worker) as pool:
        barrier = threading.Barrier(workers)
        warmups = [pool.submit(_ready, barrier) for _ in range(workers)]
        for item in warmups:
            item.result()
        cpu_started = time.process_time()
        wall_started = time.perf_counter()
        submitted = [(doc, time.perf_counter()) for doc in documents]
        futures = [pool.submit(_process, doc, dataset, stamp) for doc, stamp in submitted]
        records = []
        for completed, future in enumerate(as_completed(futures), 1):
            records.append(future.result())
            if completed % 10 == 0 or completed == len(futures):
                print(f"throughput-{workers}: {completed}/{len(futures)}", flush=True)
        wall_seconds = time.perf_counter() - wall_started
        cpu_seconds = time.process_time() - cpu_started
    stop.set()
    sampler.join(timeout=1)
    records.sort(key=lambda item: item["document_id"])
    stage_values: dict[str, list[float]] = {}
    for record in records:
        for name, value in record["stage_ms"].items():
            stage_values.setdefault(name, []).append(value)
    stage_totals = {name: sum(values) for name, values in stage_values.items()}
    accounted = sum(
        total for name, total in stage_totals.items() if not name.endswith("_detail")
    ) or 1
    stages = {
        name: {
            "calls": len(values), "total_ms": sum(values),
            "percent_of_accounted_stage_time": (
                None if name.endswith("_detail") else sum(values) / accounted
            ),
            "p50_ms": _percentile(values, .50), "p95_ms": _percentile(values, .95),
            "p99_ms": _percentile(values, .99),
        }
        for name, values in sorted(stage_values.items())
    }
    latencies = [item["processing_ms"] for item in records]
    pages_per_minute = len(records) / wall_seconds * 60
    result = {
        "dataset_id": manifest["dataset_id"], "pages": len(records),
        "worker_count": workers, "cache_state": "UNCACHED_INPUTS_WARM_MODELS",
        "wall_seconds": wall_seconds, "cpu_seconds": cpu_seconds,
        "cpu_seconds_per_page": cpu_seconds / len(records),
        "cpu_utilization_percent_of_host": (
            cpu_seconds / wall_seconds / max(1, os.cpu_count() or 1) * 100
        ),
        "memory_peak_bytes": memory_peak,
        "memory_peak_gb": memory_peak / 1024**3,
        "pages_per_minute": pages_per_minute,
        "pages_per_hour": pages_per_minute * 60,
        "documents_per_hour_at_3_pages": pages_per_minute * 20,
        "latency_ms": {
            "p50": _percentile(latencies, .50), "p95": _percentile(latencies, .95),
            "p99": _percentile(latencies, .99), "max": max(latencies),
        },
        "queue_wait_ms": {
            "p50": _percentile([item["queue_wait_ms"] for item in records], .50),
            "p95": _percentile([item["queue_wait_ms"] for item in records], .95),
        },
        "full_page_ocr_calls_per_page": sum(item["full_page_ocr_calls"] for item in records)/len(records),
        "regional_ocr_calls_per_page": sum(item["regional_ocr_calls"] for item in records)/len(records),
        "engine_initializations_per_worker": 2,
        "engine_initializations_per_page": 2 * workers / len(records),
        "stages": stages,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), "utf-8")
    output.with_suffix(".records.jsonl").write_text(
        "\n".join(json.dumps(item) for item in records) + "\n", "utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 4, 8), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, args.output, args.workers), indent=2))
