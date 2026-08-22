"""Benchmark full-page OCR geometry on annotated Bundle-D corpora."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import time
import tracemalloc
from pathlib import Path

from PIL import Image

from evaluation.generate_bundle_d_dev_v1 import DEFAULT_OUTPUT
from workers.page_detection.text_extraction import (
    PaddleOCRTextExtractor, RapidOCRFullPageTextExtractor,
)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _iou(left, right) -> float:
    x0, y0 = max(left[0], right[0]), max(left[1], right[1])
    x1, y1 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0, x1-x0) * max(0, y1-y0)
    union = ((left[2]-left[0])*(left[3]-left[1]) +
             (right[2]-right[0])*(right[3]-right[1]) - intersection)
    return intersection / union if union else 0.0


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1]+1, previous[j]+1,
                               previous[j-1] + (a != b)))
        previous = current
    return previous[-1]


def _score(expected: list[dict], actual) -> dict:
    # OCR adapters may return a word, phrase, or complete line per box.
    # Split phrase boxes proportionally so token metrics compare equivalent
    # units without altering OCR output used by extraction.
    expanded = []
    for line in actual:
        words = line.text.split()
        if len(words) <= 1:
            expanded.append(line)
            continue
        total = sum(max(len(word), 1) for word in words)
        cursor = line.x0
        for word in words:
            span = (line.x1-line.x0) * max(len(word), 1) / total
            expanded.append(type("Token", (), {"text": word, "x0": cursor,
                "y0": line.y0, "x1": cursor+span, "y1": line.y1})())
            cursor += span
    actual = expanded
    unused = set(range(len(actual)))
    matches, ious = 0, []
    for token in expected:
        choices = [(index, _iou(token["bbox"], (line.x0, line.y0, line.x1, line.y1)))
                   for index, line in enumerate(actual)
                   if index in unused and _norm(token["text"]) == _norm(line.text)]
        if not choices:
            continue
        index, overlap = max(choices, key=lambda item: item[1])
        if overlap >= .25:
            unused.remove(index); matches += 1; ious.append(overlap)
    expected_text = " ".join(_norm(item["text"]) for item in expected)
    actual_text = " ".join(_norm(item.text) for item in sorted(actual, key=lambda x: (x.y0, x.x0)))
    return {
        "true_positive_tokens": matches,
        "expected_tokens": len(expected), "predicted_tokens": len(actual),
        "token_recall": matches / len(expected) if expected else 1.0,
        "token_precision": matches / len(actual) if actual else float(not expected),
        "cer": _distance(expected_text, actual_text) / max(len(expected_text), 1),
        "mean_matched_box_iou": statistics.fmean(ious) if ious else 0.0,
    }


def benchmark(dataset: Path, engines: tuple[str, ...], limit: int | None = None) -> dict:
    truth = [json.loads(line) for line in (dataset / "ground_truth.jsonl").read_text("utf-8").splitlines()]
    if limit:
        truth = truth[:limit]
    instances = {
        "rapidocr": RapidOCRFullPageTextExtractor(),
        "paddleocr": PaddleOCRTextExtractor(),
    }
    report = {"dataset": json.loads((dataset / "manifest.json").read_text("utf-8")), "engines": {}}
    for engine_name in engines:
        extractor = instances[engine_name]
        scores, walls, cpus, peaks = [], [], [], []
        for document in truth:
            image = Image.open(dataset / document["path"]).convert("RGB")
            tracemalloc.start(); wall = time.perf_counter(); cpu = time.process_time()
            lines = extractor.extract(image)
            walls.append(time.perf_counter()-wall); cpus.append(time.process_time()-cpu)
            _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop(); peaks.append(peak)
            scores.append(_score(document["tokens"], lines))
        aggregate = {key: statistics.fmean(item[key] for item in scores)
                     for key in ("token_recall", "token_precision", "cer", "mean_matched_box_iou")}
        aggregate.update({
            "documents": len(scores), "mean_latency_seconds": statistics.fmean(walls),
            "p95_latency_seconds": sorted(walls)[max(0, math.ceil(.95*len(walls))-1)],
            "mean_cpu_seconds": statistics.fmean(cpus),
            "peak_python_memory_bytes": max(peaks),
        })
        report["engines"][engine_name] = aggregate
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--engines", nargs="+", choices=("rapidocr", "paddleocr"), default=("rapidocr", "paddleocr"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/bundle_d_dev_v1/full_page_ocr.json"))
    args = parser.parse_args()
    report = benchmark(args.dataset, tuple(args.engines), args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
