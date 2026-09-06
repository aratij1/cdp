"""Retained-config cold/warm qualification with actual downstream shadow stages."""

from __future__ import annotations

import gc
import json
import os
import time
from pathlib import Path
from typing import Any

import psutil  # type: ignore[import-untyped]
from PIL import Image

from evaluation.cdp2_comparison import latency_summary, write
from evaluation.closure_fresh_perception import TimedPreprocessing, selected_pages
from evaluation.real_archive_classification import PageRef
from evaluation.strict_identity_cached_replay import _page_result, decision_policy_manifest
from packages.claim_evidence.enablement import SourceEvidenceProvider
from packages.claim_intelligence.discovery import DiscoveryResult, NoncanonicalDiscovery
from packages.claim_intelligence.document import DocumentPage, adapt_ocr_tokens, fingerprint
from packages.claim_intelligence.models import ClaimGraph, FieldNode
from packages.claim_intelligence.pipeline import CDP2ShadowPipeline, LegacyFieldResult, LegacyResult
from packages.claim_intelligence.spatial import SpatialCandidateExtractor, merge_candidates
from packages.document_routing import MultiSignalRouter
from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr import OCRRequest, RapidOCRProvider
from workers.page_detection.text_extraction import TextLine

ROOT = Path(__file__).resolve().parents[1]


def run(
    *,
    thread_count: int = 8,
    affinity: list[int] | None = None,
    output_dir: Path | None = None,
    output_name: str = "latency_profile.local.json",
    max_side: int | None = None,
    page_limit: int = 12,
    repetitions: int = 4,
    page_indices: tuple[int, ...] | None = None,
    repetition_barrier: Any = None,
) -> dict:
    from evaluation.real_archive_classification import Observation

    output = output_dir or ROOT / "evaluation_results/closure_iteration6"
    output.mkdir(parents=True, exist_ok=True)
    if not 1 <= page_limit <= 12 or repetitions < 1:
        raise ValueError("INVALID_BENCHMARK_BOUNDS")
    limit, memory_arena = page_limit, True
    selected = selected_pages(limit)
    if page_indices is not None:
        if (
            not page_indices
            or len(set(page_indices)) != len(page_indices)
            or any(i < 0 or i >= len(selected) for i in page_indices)
        ):
            raise ValueError("INVALID_PAGE_PARTITION")
        selected = [selected[i] for i in page_indices]
    policy = decision_policy_manifest()
    router, spatial = MultiSignalRouter.load(), SpatialCandidateExtractor()
    pipeline, discovery, source_provider = (
        CDP2ShadowPipeline(),
        NoncanonicalDiscovery(),
        SourceEvidenceProvider(),
    )
    process = psutil.Process()
    original_affinity = process.cpu_affinity()
    if affinity is not None:
        process.cpu_affinity(affinity)
    provider = RapidOCRProvider(session_threads=thread_count, cpu_memory_arena=True)
    cold_tick = time.perf_counter()
    backend = provider._load_backend()
    cold_model_ms = (time.perf_counter() - cold_tick) * 1000
    if max_side is not None:
        backend.max_side_len = max_side
    from evaluation.production_latency_support import NativeTrace

    native_trace = NativeTrace(backend)
    gc_events = []
    gc_start = {}

    def gc_watch(phase, info):
        if phase == "start":
            gc_start[info["generation"]] = time.perf_counter()
        else:
            gc_events.append(
                (time.perf_counter() - gc_start.pop(info["generation"], time.perf_counter())) * 1000
            )

    gc.callbacks.append(gc_watch)
    result: dict = {
        "scope": "FRESH_PERCEPTION_AND_DOWNSTREAM_SHADOW_WITH_UNAVAILABLE_BUSINESS_CONTEXT_NOT_PRODUCTION_SLA",
        "session_constructions": 1,
        "model_initialization_ms": cold_model_ms,
        "page_order": "FIXED_IDENTICAL",
        "ocr_cache_state": "BYPASS_FRESH_INFERENCE",
        "source_file_cache": "OS_MANAGED_WARM_NOT_FLUSHED",
        "authority": "UNLABELED",
        "workers": 1,
        "cpu_affinity": process.cpu_affinity(),
        "threads": thread_count,
        "ocr_max_side": backend.max_side_len,
        "cpu_memory_arena": memory_arena,
        "logical_cpus": os.cpu_count(),
        "source_code_sha256": fingerprint(
            {
                str(p): p.read_text()
                for p in [
                    ROOT / "packages/ocr/rapidocr_provider.py",
                    ROOT / "packages/ocr/preprocessing.py",
                    ROOT / "packages/claim_intelligence/spatial.py",
                ]
            }
        ),
        "experiments": [],
    }
    for repetition in range(repetitions):
        if repetition_barrier is not None:
            repetition_barrier.wait(timeout=600)
        provider._backend = backend
        start = time.perf_counter()
        assert provider._load_backend() is backend
        acquisition_ms = (time.perf_counter() - start) * 1000
        experiment: dict = {
            "threads": thread_count or "DEFAULT",
            "model_load_ms": cold_model_ms if repetition == 0 else 0,
            "session_acquisition_ms": acquisition_ms,
            "mode": "COLD_FIRST_PASS" if repetition == 0 else "WARM_STEADY_STATE",
            "repetition": repetition,
            "pages": [],
            "new_full_page_calls": 0,
            "new_regional_calls": 0,
        }
        result["experiments"].append(experiment)
        for item in selected:
            prior, cache = item["prior"], item["cache"]
            native_trace.reset()
            started = time.perf_counter()
            cpu_before = process.cpu_times()
            switches_before = process.num_ctx_switches()
            io_before = process.io_counters()
            gc_before = len(gc_events)
            system_cpu = psutil.cpu_percent(interval=None)
            memory_before = psutil.virtual_memory().available
            asset = Path(cache["source_asset_path"])
            import hashlib

            if hashlib.sha256(asset.read_bytes()).hexdigest() != cache["source_asset_sha256"]:
                raise ValueError("SOURCE_ASSET_CHANGED")
            stages: dict[str, Any] = {
                key: None
                for key in (
                    "registration_ms",
                    "regional_ocr_ms",
                    "claim_consistency_ms",
                    "validation_ms",
                    "llm_ms",
                )
            }
            stages["source_validation_ms"] = (time.perf_counter() - started) * 1000
            provider.preprocessing = TimedPreprocessing(provider.preprocessing.config, stages)
            tick = time.perf_counter()
            with Image.open(asset) as source:
                source.seek(prior["source_page_number"] - 1)
                source_dpi = (
                    [float(v) for v in source.info["dpi"]] if source.info.get("dpi") else None
                )
                source.load()
                stages["decode_ms"] = (time.perf_counter() - tick) * 1000
                tick = time.perf_counter()
                image = source.convert("RGB")
            stages["render_ms"] = (time.perf_counter() - tick) * 1000
            ref = PageRef(
                prior["archive_id"],
                prior["package_id"],
                prior["source_asset_id"],
                prior["source_page_id"],
                prior["source_page_number"],
                prior["source_asset_page_count"],
                prior["source_asset_sequence"],
                asset,
                cache["source_asset_sha256"],
                prior["source_page_sha256"],
            )
            box = BoundingBox(
                x0=0,
                y0=0,
                x1=image.width,
                y1=image.height,
                image_width=image.width,
                image_height=image.height,
            )
            request = OCRRequest(
                ref.asset_id,
                ref.page_number,
                "__classification_observation__",
                "routing_evidence",
                ClaimFormType.UNSTRUCTURED,
                image,
                box,
                scope="FULL_PAGE",
                policy_allows_full_page=True,
                document_sha256=ref.asset_sha256,
                page_sha256=ref.page_sha256,
                source_representation_id=ref.asset_id,
            )
            raw_timings: list[float] = []

            def timed_backend(pixels, backend=backend, stages=stages, raw_timings=raw_timings):
                tick = time.perf_counter()
                raw = backend(pixels)
                stages["ocr_ms"] = (time.perf_counter() - tick) * 1000
                if isinstance(raw, tuple) and raw[1]:
                    raw_timings.extend(float(t) * 1000 for t in raw[1])
                return raw

            provider._backend = timed_backend
            tick = time.perf_counter()
            recognized = provider._extract_sync(request)
            stages["perception_ms"] = (time.perf_counter() - tick) * 1000
            stages["postprocessing_ms"] = (
                stages["perception_ms"] - stages["ocr_ms"] - stages.get("preprocess_ms", 0)
            )
            experiment["new_full_page_calls"] += 1
            tokens = recognized.candidates[0].tokens if recognized.candidates else ()
            lines = tuple(
                TextLine(
                    t.text,
                    t.bounding_box.x0,
                    t.bounding_box.y0,
                    t.bounding_box.x1,
                    t.bounding_box.y1,
                    t.confidence,
                )
                for t in tokens
            )
            observation = Observation(
                lines,
                recognized.latency_ms,
                recognized.provider,
                recognized.provider_version,
                False,
            )
            tick = time.perf_counter()
            routed = _page_result(
                ref, image, observation, router, provider.provider_version, "FRESH", policy
            )
            stages["identity_ms"] = (time.perf_counter() - tick) * 1000
            chain = routed["production_chain"]
            tick = time.perf_counter()
            page = DocumentPage(
                ref.page_id,
                ref.package_id,
                chain.get("verified_identity_family") or "UNKNOWN",
                chain.get("verification_status") or "NOT_VERIFIED",
                image.width,
                image.height,
                "UNKNOWN",
                adapt_ocr_tokens(
                    tokens,
                    page_id=ref.page_id,
                    source_id=ref.asset_sha256,
                    engine=recognized.provider,
                    invocation_id="fresh",
                    crop_hash=ref.page_sha256,
                ),
            )
            candidates = spatial.extract(page)
            stages["candidate_generation_ms"] = (time.perf_counter() - tick) * 1000
            tick = time.perf_counter()
            discovered = discovery.extract(page)
            stages["noncanonical_discovery_ms"] = (time.perf_counter() - tick) * 1000
            assembled = {
                n: merge_candidates([*candidates.get(n, []), *discovered.candidates.get(n, [])])
                for n in sorted(set(candidates) | set(discovered.candidates))
            }
            graph = ClaimGraph(
                ref.page_id,
                page.form_type,
                {n: FieldNode(n, list(v)) for n, v in assembled.items()},
                form_identity_confirmed=page.canonical_identity_confirmed,
            )
            legacy = LegacyResult(
                ref.page_id,
                tuple(
                    LegacyFieldResult(
                        n, None, False, tuple(v), evidence_blockers=("EVIDENCE_REQUIRED",)
                    )
                    for n, v in assembled.items()
                ),
                "SHADOW_NO_CANONICAL_RESULT",
                page.form_type,
            )
            tick = time.perf_counter()
            effective = pipeline.assess_document_blockers(
                legacy, DiscoveryResult(assembled), source_sha256=ref.asset_sha256
            )
            stages["effective_state_ms"] = (time.perf_counter() - tick) * 1000
            tick = time.perf_counter()
            constraints = pipeline.engine.consistency.evaluate(graph)
            stages["claim_consistency_ms"] = (time.perf_counter() - tick) * 1000
            tick = time.perf_counter()
            source_evidence = source_provider.lookup(
                package_id=ref.package_id, page_id=ref.page_id, attachment_id=ref.asset_id
            )
            stages["evidence_ms"] = (time.perf_counter() - tick) * 1000
            tick = time.perf_counter()
            shadow_decisions = pipeline.engine.evaluate(graph)
            stages["claim_graph_decision_ms"] = (time.perf_counter() - tick) * 1000
            downstream_hash = fingerprint(
                (effective, constraints, source_evidence.status, source_evidence.reason)
            )
            semantics = [(t.text, t.bounding_box.model_dump(), t.confidence) for t in tokens]
            values = [(t.text, t.bounding_box.model_dump()) for t in tokens]
            record = {
                "page_id": fingerprint(ref.page_id),
                "package_id": fingerprint(ref.package_id),
                "dimensions": [image.width, image.height],
                "source_dpi": source_dpi,
                "source_pixels": image.width * image.height,
                "native_trace": native_trace.report(),
                "candidate_ids_sha256": fingerprint(assembled),
                "claim_graph_decisions_sha256": fingerprint(shadow_decisions),
                "canonical_routing_decisions_sha256": fingerprint(chain),
                "tokens": len(tokens),
                "cache_hit": False,
                "memory_rss_bytes": process.memory_info().rss,
                "peak_working_set_bytes": getattr(process.memory_info(), "peak_wset", None),
                "system_available_memory_before": memory_before,
                "system_cpu_percent_previous_interval": system_cpu,
                "process_cpu_ms": 1000
                * (
                    (process.cpu_times().user - cpu_before.user)
                    + (process.cpu_times().system - cpu_before.system)
                ),
                "context_switches": process.num_ctx_switches().voluntary
                - switches_before.voluntary,
                "process_read_bytes": process.io_counters().read_bytes - io_before.read_bytes,
                "gc_pause_ms": sum(gc_events[gc_before:]),
                "downstream_semantics_sha256": downstream_hash,
                "effective_fields": len(effective),
                "full_claim_context_available": False,
                "full_page_ocr_calls": 1,
                "stages": stages,
                "ocr_internal_ms": raw_timings,
                "token_evidence_sha256": fingerprint(semantics),
                "text_geometry_sha256": fingerprint(values),
                "candidate_semantics_sha256": fingerprint(
                    {k: [(c.value, c.features) for c in v] for k, v in candidates.items()}
                ),
                "candidate_counts": {k: len(v) for k, v in candidates.items()},
                "strict_family": page.form_type,
                "identity_confirmed": page.canonical_identity_confirmed,
                "canonical_localization_invoked": chain["actual_localization_invoked"],
            }
            tick = time.perf_counter()
            json.dumps(record, sort_keys=True)
            stages["serialization_ms"] = (time.perf_counter() - tick) * 1000
            stages["total_ms"] = (time.perf_counter() - started) * 1000
            experiment["pages"].append(record)
            experiment["latency"] = latency_summary(
                [r["stages"]["total_ms"] for r in experiment["pages"]]
            )
            experiment["latency"]["throughput_pages_per_second"] = experiment["latency"].pop(
                "throughput_claims_per_second"
            )
            io_tick = time.perf_counter()
            write(output, output_name, result)
            stages["report_io_ms_outside_page_latency"] = (time.perf_counter() - io_tick) * 1000
            print(
                json.dumps(
                    {
                        "threads": thread_count,
                        "completed": len(experiment["pages"]),
                        "total_ms": stages["total_ms"],
                    }
                ),
                flush=True,
            )
        provider._backend = backend
    if len(result["experiments"]) > 1:
        base = result["experiments"][0]["pages"]
        for e in result["experiments"][1:]:
            e["exact_token_evidence_equal"] = all(
                a["token_evidence_sha256"] == b["token_evidence_sha256"]
                for a, b in zip(base, e["pages"], strict=True)
            )
            e["text_geometry_equal"] = all(
                a["text_geometry_sha256"] == b["text_geometry_sha256"]
                for a, b in zip(base, e["pages"], strict=True)
            )
    write(output, output_name, result)
    gc.callbacks.remove(gc_watch)
    native_trace.restore()
    process.cpu_affinity(original_affinity)
    return result


if __name__ == "__main__":
    run()
