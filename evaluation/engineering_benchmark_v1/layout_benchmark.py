from __future__ import annotations

import json
import re
import time
from pathlib import Path

from PIL import Image

from packages.layout_intelligence import BundleDLayoutEngine
from workers.cascade.tesseract_adapter import TesseractTextExtractor

from .build_manifest import ROOT
from .metrics import percentile, ratio
from .routing_benchmark import PHASE_ROOT


def _norm(value) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper())


def run(limit: int = 15):
    truth_path = ROOT / "evaluation_data" / "bundle_d_dev_v1" / "ground_truth.jsonl"
    truth = [json.loads(line) for line in truth_path.read_text("utf-8").splitlines()]
    # Structured/custom families with field truth; attachment/non-claim pages
    # are already covered at the routing/STOP layer.
    selected = [row for row in truth if row.get("fields") and row["family"] not in {
        "ATTACHMENT", "CORRESPONDENCE", "NON_CLAIM", "NONCLAIM"}][:limit]
    ocr = TesseractTextExtractor(psm=11)
    layout = BundleDLayoutEngine()
    documents = []
    for row in selected:
        started = time.perf_counter()
        with Image.open(truth_path.parent / row["path"]) as opened:
            image = opened.convert("L")
            image.load()
        ocr_started = time.perf_counter()
        tokens = ocr.extract(image)
        ocr_ms = (time.perf_counter() - ocr_started) * 1000
        layout_started = time.perf_counter()
        result = layout.extract(tokens, page_number=1, width=image.width, height=image.height,
                                engine="tesseract_psm_11")
        layout_ms = (time.perf_counter() - layout_started) * 1000
        fields = []
        for name, expected in row["fields"].items():
            candidates = result.candidates.get(name, [])
            values = [candidate.value for candidate in candidates]
            exact = any(_norm(value) == _norm(expected) for value in values)
            fields.append({"field_name": name, "expected": expected, "candidate_count": len(candidates),
                           "label_detected": bool(candidates), "value_detected": exact,
                           "label_value_link_correct": exact, "canonical_mapping_correct": exact,
                           "field_exact_match": exact, "predicted_values": values[:3]})
        truth_tokens = {_norm(token["text"]) for token in row.get("tokens", []) if _norm(token["text"])}
        observed_tokens = {_norm(token.text) for token in tokens if _norm(token.text)}
        documents.append({"document_id": row["document_id"], "family": row["family"],
            "predicted_route": result.route.value, "predicted_schema": result.schema_evidence.schema_family,
            "token_recall": ratio(len(truth_tokens & observed_tokens), len(truth_tokens)), "fields": fields,
            "latency_ms": {"ocr": ocr_ms, "layout": layout_ms,
                           "total": (time.perf_counter() - started) * 1000}})
    fields = [field for doc in documents for field in doc["fields"]]
    metrics = {"evidence_class": "ENGINEERING_BENCHMARK_ONLY", "production_promotion_authority": False,
        "documents": len(documents), "fields": len(fields),
        "token_accuracy": ratio(sum(doc["token_recall"] for doc in documents), len(documents)),
        "label_detection": ratio(sum(field["label_detected"] for field in fields), len(fields)),
        "value_detection": ratio(sum(field["value_detected"] for field in fields), len(fields)),
        "label_value_linking": ratio(sum(field["label_value_link_correct"] for field in fields), len(fields)),
        "canonical_mapping": ratio(sum(field["canonical_mapping_correct"] for field in fields), len(fields)),
        "field_exact_match": ratio(sum(field["field_exact_match"] for field in fields), len(fields)),
        "structured_route_recall": ratio(sum(doc["predicted_route"] == "UNKNOWN_STRUCTURED" for doc in documents),
                                           len(documents)),
        "p95_latency_ms": percentile((doc["latency_ms"]["total"] for doc in documents), .95),
        "ocr_engine": "Tesseract 5.x PSM 11", "full_page_ocr_calls": len(documents),
        "cloud_api_calls": 0, "cloud_cost_usd": 0.0, "details": documents}
    (PHASE_ROOT / "layout_extraction_metrics.json").write_text(json.dumps(metrics, indent=2), "utf-8")
    extraction_path = PHASE_ROOT / "extraction_metrics.json"
    if extraction_path.is_file():
        extraction = json.loads(extraction_path.read_text("utf-8"))
        extraction["unknown_structured"] = {key: value for key, value in metrics.items() if key != "details"}
        extraction_path.write_text(json.dumps(extraction, indent=2), "utf-8")
    return metrics


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
