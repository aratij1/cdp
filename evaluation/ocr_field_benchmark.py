"""Compare OCR engines by field on PHI-free, explicitly cropped fixtures."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from time import perf_counter

from PIL import Image

from evaluation.raw_error_analysis import _norm
from workers.cascade.tesseract_adapter import for_field_type
from workers.page_detection.text_extraction import (
    ModelNotAvailableError, PaddleOCRTextExtractor, RapidOCRTextExtractor,
)

ROOT = Path(__file__).resolve().parents[1]
FIELD_TYPES = {
    "patient_dob": "date", "provider_npi": "npi", "total_charge": "currency",
    "total_charges": "currency", "type_of_bill": "code", "principal_diagnosis": "code",
    "federal_tax_no": "tax_id", "insured_id_number": "code", "patient_name": "text",
}


def character_error_rate(expected: str, actual: str) -> float:
    left, right = _norm(expected), _norm(actual)
    previous = list(range(len(right) + 1))
    for index, lchar in enumerate(left, 1):
        current = [index]
        for offset, rchar in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[offset] + 1,
                               previous[offset - 1] + (lchar != rchar)))
        previous = current
    return previous[-1] / max(1, len(left))


def summarize(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["field_name"], row["engine"])].append(row)
    output = []
    for (field, engine), values in sorted(grouped.items()):
        available = [row for row in values if row.get("available", True)]
        output.append({
            "field_name": field, "engine": engine, "evaluated": len(available),
            "exact_match": sum(row["exact"] for row in available),
            "exact_accuracy": sum(row["exact"] for row in available) / len(available) if available else None,
            "mean_character_error_rate": sum(row["character_error_rate"] for row in available) / len(available) if available else None,
            "mean_latency_ms": sum(row["latency_ms"] for row in available) / len(available) if available else None,
            "ocr_accuracy_given_correct_crop": (
                sum(row["exact"] for row in available if row["crop_correct"]) /
                sum(row["crop_correct"] for row in available)
            ) if any(row["crop_correct"] for row in available) else None,
        })
    return output


def _extract(engine: str, image: Image.Image, field_type: str, instances: dict) -> tuple[str | None, float]:
    if engine == "tesseract":
        extractor = instances.setdefault((engine, field_type), for_field_type(field_type))
        lines = extractor.extract(image)
    elif engine == "rapidocr":
        extractor = instances.setdefault(engine, RapidOCRTextExtractor())
        lines = extractor.extract_region(image, 0, 0, image.width, image.height)
    elif engine == "paddleocr":
        extractor = instances.setdefault(engine, PaddleOCRTextExtractor())
        lines = extractor.extract_region(image, 0, 0, image.width, image.height)
    else:
        raise ValueError(f"unsupported OCR engine: {engine}")
    return " ".join(line.text for line in lines).strip() or None, (
        sum(line.confidence for line in lines) / len(lines) if lines else 0.0
    )


def run(dataset: Path, fields: set[str], engines: list[str]) -> tuple[list[dict], list[dict]]:
    truth = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))["documents"]
    instances: dict = {}; rows = []
    unavailable: set[str] = set()
    for document in truth:
        for field in document["fields"]:
            name = field["field_name"]
            if fields and name not in fields:
                continue
            crop_path = dataset / "crops" / document["document_id"] / f"{name}.png"
            with Image.open(crop_path) as source:
                crop = source.convert("RGB")
            values: dict[str, str | None] = {}
            for engine in engines:
                if engine in unavailable:
                    continue
                started = perf_counter()
                try:
                    value, confidence = _extract(engine, crop, FIELD_TYPES.get(name, "text"), instances)
                except (ModelNotAvailableError, ImportError):
                    unavailable.add(engine); continue
                latency = (perf_counter() - started) * 1000
                values[engine] = value
                rows.append({
                    "document_id": document["document_id"], "document_family": document["form_type"],
                    "field_name": name, "engine": engine, "expected": field["expected_raw"],
                    "value": value, "confidence": confidence, "latency_ms": latency,
                    "exact": _norm(value) == _norm(field["expected_raw"]),
                    "character_error_rate": character_error_rate(field["expected_raw"], value or ""),
                    "crop_correct": True,
                    "crop_qualification": "SYNTHETIC_RENDERER_CONTRACT_NOT_MANUAL_VISUAL_REVIEW",
                })
            agreement = {engine: sum(_norm(value) == _norm(other) for other in values.values())
                         for engine, value in values.items()}
            for row in rows[-len(values):]:
                row["engine_agreement_count"] = agreement[row["engine"]]
    return rows, summarize(rows)


def _markdown(summary: list[dict]) -> str:
    lines = [
        "# CDP OCR by Field Benchmark", "",
        "> Synthetic correct-crop benchmark; not production accuracy.", "",
        "| Field | Engine | Evaluated | Exact | Accuracy | CER | Mean latency | OCR accuracy given correct crop |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary:
        display = lambda value: "unavailable" if value is None else f"{value:.2%}"
        latency = "unavailable" if item["mean_latency_ms"] is None else f"{item['mean_latency_ms']:.1f} ms"
        lines.append(
            f"| `{item['field_name']}` | {item['engine']} | {item['evaluated']} | {item['exact_match']} | "
            f"{display(item['exact_accuracy'])} | {display(item['mean_character_error_rate'])} | "
            f"{latency} | {display(item['ocr_accuracy_given_correct_crop'])} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation_data/synthetic_public_v3")
    parser.add_argument("--fields", nargs="*", default=[])
    parser.add_argument("--engines", nargs="+", default=["rapidocr", "tesseract", "paddleocr"])
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation_results/raw_accuracy_recovery/ocr_by_field")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/CDP_OCR_BY_FIELD_BENCHMARK.md")
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    rows, summary = run(args.dataset, set(args.fields), args.engines)
    (args.output / "predictions.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    args.report.write_text(_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
