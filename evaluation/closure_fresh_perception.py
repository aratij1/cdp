"""Fresh RapidOCR timing experiments; PHI stays in memory, output is hashes/counts."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

import psutil
from PIL import Image

from evaluation.cdp2_comparison import latency_summary, write
from evaluation.real_archive_classification import PageRef
from evaluation.strict_identity_cached_replay import _page_result, decision_policy_manifest
from packages.claim_intelligence.document import DocumentPage, adapt_ocr_tokens, fingerprint
from packages.claim_intelligence.spatial import SpatialCandidateExtractor
from packages.document_routing import MultiSignalRouter
from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr import OCRRequest, RapidOCRProvider
from packages.ocr.preprocessing import PreprocessingRegistry
from workers.page_detection.text_extraction import TextLine

ROOT = Path(__file__).resolve().parents[1]


class TimedPreprocessing(PreprocessingRegistry):
    def __init__(self, config: dict, stages: dict):
        super().__init__(config)
        self.stages = stages

    def apply(self, image, field_name, field_type, requested=None):
        start = time.perf_counter()
        result = super().apply(image, field_name, field_type, requested)
        self.stages["preprocess_ms"] = (time.perf_counter() - start) * 1000
        return result


def selected_pages(limit: int = 6) -> list[dict]:
    records = [
        json.loads(p.read_text())
        for p in sorted((ROOT / "evaluation_data/strict_identity_replay_v3/pages").glob("*.json"))
    ]
    chosen = [r for r in records if r["production_chain"]["localization_authorized"]]
    counts: Counter[str] = Counter(r["candidate_class"] for r in chosen)
    remaining = [r for r in records if r not in chosen]
    while len(chosen) < limit and remaining:
        row = min(remaining, key=lambda r: (counts[r["candidate_class"]], r["source_page_id"]))
        chosen.append(row)
        counts[row["candidate_class"]] += 1
        remaining.remove(row)
    ids = {r["source_page_id"] for r in chosen}
    caches = {}
    for path in (ROOT / "evaluation_data/strict_identity_replay_v2/ocr_cache").glob("*.json"):
        cache = json.loads(path.read_text())
        if cache["source_page_id"] in ids:
            caches[cache["source_page_id"]] = cache
    return [{"prior": r, "cache": caches[r["source_page_id"]]} for r in chosen[:limit]]


def run(
    limit: int,
    threads: list[int],
    output_name: str = "fresh_perception.json",
    *,
    memory_arena: bool = False,
) -> dict:
    from evaluation.real_archive_classification import Observation

    output = ROOT / "evaluation_results/closure"
    selected = selected_pages(limit)
    policy = decision_policy_manifest()
    router, spatial = MultiSignalRouter.load(), SpatialCandidateExtractor()
    result: dict = {
        "scope": "FRESH_OCR_ROUTING_SPATIAL_SHADOW_NOT_COMPLETE_CLAIM_PROCESSING",
        "authority": "UNLABELED",
        "workers": 1,
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
    for thread_count in threads:
        provider = RapidOCRProvider(
            session_threads=thread_count or None, cpu_memory_arena=memory_arena
        )
        start = time.perf_counter()
        backend = provider._load_backend()
        model_load_ms = (time.perf_counter() - start) * 1000
        experiment: dict = {
            "threads": thread_count or "DEFAULT",
            "model_load_ms": model_load_ms,
            "pages": [],
            "new_full_page_calls": 0,
            "new_regional_calls": 0,
        }
        result["experiments"].append(experiment)
        for item in selected:
            prior, cache = item["prior"], item["cache"]
            started = time.perf_counter()
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
            stages["preprocess_and_assembly_ms"] = stages["perception_ms"] - stages["ocr_ms"]
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
            semantics = [(t.text, t.bounding_box.model_dump(), t.confidence) for t in tokens]
            values = [(t.text, t.bounding_box.model_dump()) for t in tokens]
            record = {
                "page_id": fingerprint(ref.page_id),
                "package_id": fingerprint(ref.package_id),
                "dimensions": [image.width, image.height],
                "tokens": len(tokens),
                "cache_hit": False,
                "memory_rss_bytes": psutil.Process().memory_info().rss,
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
            write(output, output_name, result)
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
        provider._backend = None
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
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=6)
    parser.add_argument("--threads", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--output-name", default="fresh_perception.json")
    parser.add_argument("--memory-arena", action="store_true")
    args = parser.parse_args()
    run(args.pages, args.threads, args.output_name, memory_arena=args.memory_arena)
