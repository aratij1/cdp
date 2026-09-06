"""Profile strict identity on fixed cached observations without logging OCR text."""

from __future__ import annotations

import cProfile
import json
import pstats
import time
from collections import Counter

from PIL import Image

from evaluation.closure_fresh_perception import selected_pages
from evaluation.production_accelerator_probe import OUT, ROOT
from evaluation.strict_identity_cached_replay import observation_from_cache
from packages.document_routing import MultiSignalRouter


def run() -> dict:
    router = MultiSignalRouter.load()
    profile = cProfile.Profile()
    times = []
    for item in selected_pages(12):
        cache, prior = item["cache"], item["prior"]
        with Image.open(cache["source_asset_path"]) as source:
            source.seek(prior["source_page_number"] - 1)
            image = source.convert("RGB")
        observation = observation_from_cache(cache)
        start = time.perf_counter()
        profile.runcall(router.route, image, list(observation.lines))
        times.append((time.perf_counter() - start) * 1000)
    stats = pstats.Stats(profile)
    totals: Counter = Counter()
    calls: Counter = Counter()
    measured_stats = stats.stats  # type: ignore[attr-defined]
    for (filename, _, name), (primitive, total, own, cumulative, _) in measured_stats.items():
        if "document_routing" in filename or "difflib" in filename:
            label = filename.replace("\\", "/").split("/")[-1] + ":" + name
            totals[label] += own * 1000
            calls[label] += total
    report = {
        "scope": "STRICT_ROUTER_CPU_PROFILE_CACHED_OCR_NOT_FRESH_PAGE_LATENCY",
        "pages": len(times),
        "profiler_overhead_included": True,
        "total_profiled_ms": sum(times),
        "new_ocr_calls": 0,
        "top_exclusive_contributors": [
            {"function": k, "exclusive_ms": v, "calls": calls[k]} for k, v in totals.most_common(12)
        ],
        "decision": "RETAIN_STRICT_IDENTITY",
        "reason": "No validated fast path replaces required phrase, geometry and identity checks. Repeated-page caching cannot reduce fresh unique-page OCR latency.",
        "production_semantics_changed": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / "docs/closure/form_identity_profile.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


if __name__ == "__main__":
    run()
