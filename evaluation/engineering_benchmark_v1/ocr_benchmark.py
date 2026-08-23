from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from typing import Any

from PIL import Image

from workers.cascade.tesseract_adapter import for_field_type
from workers.page_detection.text_extraction import PaddleOCRTextExtractor, RapidOCRTextExtractor

from .build_manifest import ROOT, build_manifest
from .metrics import percentile, ratio
from .routing_benchmark import PHASE_ROOT


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper())


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, 1):
        current = [left_index]
        for right_index, right_char in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[right_index] + 1,
                               previous[right_index - 1] + (left_char != right_char)))
        previous = current
    return previous[-1]


def _field_type(name: str) -> str:
    lowered = name.casefold()
    if "date" in lowered or "dob" in lowered:
        return "date"
    if "npi" in lowered:
        return "npi"
    if "charge" in lowered or "amount" in lowered:
        return "currency"
    if "zip" in lowered:
        return "zip"
    if "id" in lowered or "diagnosis" in lowered or "bill" in lowered:
        return "code"
    return "text"


def _read(engine, image: Image.Image, box: tuple[int, int, int, int]) -> tuple[str, float]:
    lines = engine.extract_region(image, *box)
    lines = sorted(lines, key=lambda line: (line.y0, line.x0))
    return " ".join(line.text for line in lines), (
        sum(line.confidence for line in lines) / len(lines) if lines else 0.0)


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [row for row in rows if row["available"]]
    result: dict[str, Any] = {
        "evidence_class": "ENGINEERING_BENCHMARK_ONLY", "production_promotion_authority": False,
        "crop_trials": len(rows), "successful_trials": len(available), "cloud_api_calls": 0,
        "cloud_cost_usd": 0.0, "by_engine": {}, "by_form": {}, "by_field": {},
        "best_engine_by_field": {}, "unavailable": [row for row in rows if not row["available"]],
    }
    def summary(items):
        return {"trials": len(items), "exact_match": ratio(sum(item["exact"] for item in items), len(items)),
                "mean_cer": ratio(sum(item["cer"] for item in items), len(items)),
                "p50_latency_ms": percentile((item["latency_ms"] for item in items), .50),
                "p95_latency_ms": percentile((item["latency_ms"] for item in items), .95)}
    for key, target in (("engine", result["by_engine"]), ("family", result["by_form"]),
                        ("field_name", result["by_field"])):
        for value in sorted({row[key] for row in available}):
            target[value] = summary([row for row in available if row[key] == value])
    for field in sorted({row["field_name"] for row in available}):
        candidates = {}
        for engine in sorted({row["engine"] for row in available}):
            items = [row for row in available if row["field_name"] == field and row["engine"] == engine]
            if items:
                candidates[engine] = summary(items)
        if candidates:
            best = max(candidates, key=lambda engine: (candidates[engine]["exact_match"],
                                                       -candidates[engine]["mean_cer"],
                                                       -candidates[engine]["p95_latency_ms"]))
            result["best_engine_by_field"][field] = {"engine": best, **candidates[best],
                                                     "all_engines": candidates}
    return result


def run(documents_per_family: int = 4) -> dict[str, Any]:
    manifest = build_manifest()
    selected = []
    for family in ("CMS1500", "UB04"):
        records = [row for row in manifest.records if row.expected_family == family and row.crop_boxes]
        records.sort(key=lambda row: (row.quality_bucket, row.document_id))
        by_quality = defaultdict(list)
        for record in records:
            by_quality[record.quality_bucket].append(record)
        # Round-robin qualities so a small bounded engine comparison is not
        # accidentally a clean-scan-only result.
        chosen = []
        while len(chosen) < documents_per_family and any(by_quality.values()):
            for quality in sorted(by_quality):
                if by_quality[quality] and len(chosen) < documents_per_family:
                    chosen.append(by_quality[quality].pop(0))
        selected.extend(chosen)
    rapid = RapidOCRTextExtractor()
    paddle = PaddleOCRTextExtractor(cpu_threads=2)
    rows = []
    for document_index, record in enumerate(selected, 1):
        with Image.open(ROOT / record.image_path) as opened:
            image = opened.convert("L")
            image.load()
        for field_name, box in record.crop_boxes.items():
            expected = record.truth_fields.get(field_name, "")
            engines = {"rapidocr": rapid, "paddleocr": paddle,
                       "tesseract": for_field_type(_field_type(field_name))}
            for engine_name, engine in engines.items():
                started = time.perf_counter()
                try:
                    text, confidence = _read(engine, image, tuple(box))
                    available, error = True, None
                except Exception as exc:  # engine availability is benchmark evidence, not a crash
                    text, confidence, available, error = "", 0.0, False, f"{type(exc).__name__}: {exc}"
                observed, wanted = _norm(text), _norm(expected)
                rows.append({"document_id": record.document_id, "family": record.expected_family,
                    "quality_bucket": record.quality_bucket, "field_name": field_name,
                    "field_type": _field_type(field_name), "engine": engine_name,
                    "expected": str(expected), "observed": text, "confidence": confidence,
                    "exact": available and observed == wanted,
                    "cer": ratio(_distance(observed, wanted), max(1, len(wanted))),
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "available": available, "error": error})
        if document_index % 5 == 0:
            print(json.dumps({"ocr_documents_completed": document_index,
                              "ocr_documents_total": len(selected)}), flush=True)
    metrics = _aggregate(rows)
    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    (PHASE_ROOT / "ocr_by_field.json").write_text(json.dumps(metrics, indent=2), "utf-8")
    (PHASE_ROOT / "ocr_trials.jsonl").write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n", "utf-8")
    return metrics


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
