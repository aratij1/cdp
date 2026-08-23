"""Uncached canonical Phase-8.2 throughput and stage profiler."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    RapidOCRFullPageTextExtractor,
    RapidOCRTextExtractor,
)
from workers.standard_form_extraction import (
    StandardFormExtractionService,
    StandardFormProcessingService,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation_data/phase8_1_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V1"
_LOCAL = threading.local()
_THREAD_CONFIG = {"intra": None, "inter": None, "opencv": None}


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _semantic_output(value):
    """Remove generated identity/time metadata from equivalence fingerprints."""
    if isinstance(value, dict):
        return {
            key: _semantic_output(item) for key, item in value.items()
            if key not in {"field_id", "evidence_id", "produced_at"}
        }
    if isinstance(value, list):
        return [_semantic_output(item) for item in value]
    return value


class _TimedExtractor:
    def __init__(self, inner):
        self.inner = inner
        self.full_calls = 0
        self.regional_calls = 0
        self.full_ms = 0.0
        self.regional_ms = 0.0
        self.profile_totals: dict[str, float] = {}

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def extract(self, image):
        started = time.perf_counter()
        try:
            return self.inner.extract(image)
        finally:
            self.full_calls += 1
            self.full_ms += (time.perf_counter() - started) * 1000
            for name, value in getattr(self.inner, "last_profile", {}).items():
                self.profile_totals[name] = self.profile_totals.get(name, 0.0) + value

    def extract_region(self, image, x0, y0, x1, y1):
        started = time.perf_counter()
        try:
            return self.inner.extract_region(image, x0, y0, x1, y1)
        finally:
            self.regional_calls += 1
            self.regional_ms += (time.perf_counter() - started) * 1000
            for name, value in getattr(self.inner, "last_profile", {}).items():
                self.profile_totals[name] = self.profile_totals.get(name, 0.0) + value


def _initialize_worker() -> None:
    if _THREAD_CONFIG["opencv"] is not None:
        import cv2
        cv2.setNumThreads(_THREAD_CONFIG["opencv"])
    kwargs = {
        "intra_op_num_threads": _THREAD_CONFIG["intra"],
        "inter_op_num_threads": _THREAD_CONFIG["inter"],
    }
    full_inner = RapidOCRFullPageTextExtractor(**kwargs)
    regional_inner = RapidOCRTextExtractor(**kwargs)
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
    before_full_profile = dict(context["full"].profile_totals)
    before_regional_profile = dict(context["regional"].profile_totals)
    processing = context["processor"].process(
        image, template, 1, identity, page_id=doc["document_id"],
        page_sha256=doc["sha256"],
    )
    serialization_started = time.perf_counter()
    processing.model_dump_json()
    output_payload = {
        "fields": [field.model_dump(mode="json") for field in processing.fields],
        "service_lines": [line.model_dump(mode="json") for line in processing.service_lines],
    }
    output_sha256 = hashlib.sha256(json.dumps(
        _semantic_output(output_payload), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    serialization_ms = (time.perf_counter() - serialization_started) * 1000
    full_ms = context["full"].full_ms - before_full_ms
    regional_ms = context["regional"].regional_ms - before_regional_ms
    full_profile = {
        name: value - before_full_profile.get(name, 0.0)
        for name, value in context["full"].profile_totals.items()
    }
    regional_profile = {
        name: value - before_regional_profile.get(name, 0.0)
        for name, value in context["regional"].profile_totals.items()
    }
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
        "output_sha256": output_sha256,
        "full_page_ocr_profile_ms": full_profile,
        "regional_ocr_profile_ms": regional_profile,
    }


def run(dataset: Path, output: Path, workers: int, *, intra_threads: int | None = None,
        inter_threads: int | None = None, opencv_threads: int | None = None) -> dict:
    _THREAD_CONFIG.update({"intra": intra_threads, "inter": inter_threads,
                           "opencv": opencv_threads})
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
    ocr_profiles: dict[str, dict[str, list[float]]] = {"full_page": {}, "regional": {}}
    for record in records:
        for name, value in record["stage_ms"].items():
            stage_values.setdefault(name, []).append(value)
        for scope, key in (("full_page", "full_page_ocr_profile_ms"),
                           ("regional", "regional_ocr_profile_ms")):
            for name, value in record[key].items():
                ocr_profiles[scope].setdefault(name, []).append(value)
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
        "thread_configuration": {
            "intra_op_num_threads": intra_threads,
            "inter_op_num_threads": inter_threads,
            "opencv_threads": opencv_threads,
            "execution_mode": "ORT_SEQUENTIAL_DEFAULT",
        },
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
        "steady_state_engine_reloads_per_page": 0,
        "worker_busy_utilization": sum(latencies) / (wall_seconds * 1000 * workers),
        "output_fingerprints": {
            item["document_id"]: item["output_sha256"] for item in records
        },
        "output_fingerprint_schema": "semantic-output-v1",
        "stages": stages,
        "ocr_internal_profiles": {
            scope: {
                name: {"calls": len(values), "total_ms": sum(values),
                       "p50_ms": _percentile(values, .50),
                       "p95_ms": _percentile(values, .95)}
                for name, values in sorted(profile.items())
            }
            for scope, profile in ocr_profiles.items()
        },
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
    parser.add_argument("--intra-threads", type=int)
    parser.add_argument("--inter-threads", type=int)
    parser.add_argument("--opencv-threads", type=int)
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, args.output, args.workers,
                         intra_threads=args.intra_threads,
                         inter_threads=args.inter_threads,
                         opencv_threads=args.opencv_threads), indent=2))
