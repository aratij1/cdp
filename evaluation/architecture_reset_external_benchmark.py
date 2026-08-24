"""Credential-gated AWS Textract oracle for the architecture reset.

This harness never changes runtime decisions and never reads the locked holdout.
The default operation only writes a deterministic manifest. Network execution
requires an explicit data/cost acknowledgement and AWS credentials.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import time
from hashlib import sha256
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation_results/phase8_10"
DATA = ROOT / "evaluation_data/phase8_8_generalization"
ACK = "AWS_TEXTRACT_COST_AND_DATA_APPROVED"


def _canonical(value: object) -> str:
    return " ".join(str(value or "").strip().upper().split())


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def build_manifest(limit: int = 40) -> list[dict]:
    candidates: list[dict] = []
    controls: list[dict] = []
    for source in ("SOURCE_A", "SOURCE_B", "SOURCE_C"):
        records = _rows(RESULTS / source.lower() / "v3_extraction/field_records.jsonl")
        for row in records:
            if row.get("dataset_role") != "VALIDATION" or not row.get("predicted_bbox"):
                continue
            item = {
                "source": source,
                "document_id": row["document_id"],
                "field_name": row["field_name"],
                "family": row["family"],
                "critical": bool(row["critical"]),
                "image": next(
                    str(path.relative_to(ROOT)).replace("\\", "/")
                    for path in (DATA / source).rglob(f"{row['document_id']}.*")
                ),
                "bbox": row["predicted_bbox"],
                "expected": row["expected"],
                "cdp_value": row.get("final"),
                "cdp_correct": bool(row["exact"]),
                "expected_value_in_region": bool(row["expected_value_in_region"]),
            }
            if not row["exact"] and row["expected_value_in_region"]:
                candidates.append(item)
            elif row["exact"] and row["expected_value_in_region"]:
                controls.append(item)
    candidates.sort(key=lambda item: (item["source"], item["document_id"], item["field_name"]))
    controls.sort(key=lambda item: (item["source"], item["document_id"], item["field_name"]))
    hard_count = min(len(candidates), max(1, round(limit * 0.75)))
    return (candidates[:hard_count] + controls[: max(0, limit - hard_count)])[:limit]


def _crop_bytes(item: dict) -> bytes:
    image = Image.open(ROOT / item["image"]).convert("RGB")
    crop = image.crop(tuple(round(value) for value in item["bbox"]))
    output = io.BytesIO()
    crop.save(output, format="PNG")
    return output.getvalue()


def run_textract(manifest: list[dict], region: str) -> dict:
    if os.getenv("CDP_EXTERNAL_BENCHMARK_ACK") != ACK:
        raise RuntimeError("BLOCKED_EXTERNAL_PROCESSING_ACK")
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("BLOCKED_EXTERNAL_PROVIDER_SDK") from exc
    client = boto3.client("textract", region_name=region)
    rows = []
    for item in manifest:
        payload = _crop_bytes(item)
        started = time.monotonic()
        response = client.detect_document_text(Document={"Bytes": payload})
        elapsed = (time.monotonic() - started) * 1000
        value = " ".join(
            str(block.get("Text", ""))
            for block in response.get("Blocks", [])
            if block.get("BlockType") == "LINE"
        ).strip()
        rows.append({
            **item,
            "crop_sha256": sha256(payload).hexdigest(),
            "external_value": value,
            "external_correct": _canonical(value) == _canonical(item["expected"]),
            "latency_ms": elapsed,
            "estimated_cost_usd": 0.0015,
        })
    latencies = [row["latency_ms"] for row in rows]
    critical = [row for row in rows if row["critical"]]
    return {
        "status": "COMPLETE",
        "provider": "AWS Textract DetectDocumentText",
        "pages": len(rows),
        "cdp_accuracy": sum(row["cdp_correct"] for row in rows) / max(1, len(rows)),
        "external_accuracy": sum(row["external_correct"] for row in rows) / max(1, len(rows)),
        "cdp_critical_accuracy": sum(row["cdp_correct"] for row in critical)
        / max(1, len(critical)),
        "external_critical_accuracy": sum(row["external_correct"] for row in critical)
        / max(1, len(critical)),
        "cdp_only_wins": sum(row["cdp_correct"] and not row["external_correct"] for row in rows),
        "external_only_wins": sum(row["external_correct"] and not row["cdp_correct"] for row in rows),
        "both_wrong": sum(not row["external_correct"] and not row["cdp_correct"] for row in rows),
        "cost_usd": sum(row["estimated_cost_usd"] for row in rows),
        "latency_ms": {
            "p50": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RESULTS / "external_benchmark")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest(args.limit)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    if not args.execute:
        result = {"status": "BLOCKED_EXTERNAL_CREDENTIALS", "pages_planned": len(manifest)}
    else:
        result = run_textract(manifest, args.region)
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
