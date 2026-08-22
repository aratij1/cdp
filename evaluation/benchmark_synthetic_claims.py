"""Run local Tesseract against deterministic synthetic field crops."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from time import monotonic

from PIL import Image

from workers.cascade.tesseract_adapter import for_field_type


def _norm(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evaluation_data/synthetic_public_v1"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/synthetic_public_v1"))
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    truth = json.loads((args.dataset / "ground_truth.json").read_text("utf-8"))["documents"]
    manifest = json.loads((args.dataset / "document_manifest.json").read_text("utf-8"))
    predictions, counters, latencies = [], defaultdict(lambda: [0, 0]), []
    type_map = {"patient_dob": "date", "provider_npi": "npi", "total_charge": "currency",
                "total_charges": "currency", "type_of_bill": "code", "principal_diagnosis": "code",
                "federal_tax_no": "tax_id", "insured_id_number": "code", "patient_name": "text"}
    for document in truth:
        document_id = document["document_id"]
        predicted_fields = []
        for field in document["fields"]:
            name = field["field_name"]
            crop_path = args.dataset / "crops" / document_id / f"{name}.png"
            started = monotonic()
            with Image.open(crop_path) as crop:
                words = for_field_type(type_map.get(name, "text")).extract(crop.convert("RGB"))
            latencies.append((monotonic() - started) * 1000)
            value = " ".join(word.text for word in words).strip() or None
            correct = _norm(value) == _norm(field["expected_raw"])
            for key in ("overall", f"family:{document['form_type']}",
                        f"condition:{manifest[document_id]['condition']}", f"field:{name}"):
                counters[key][1] += 1; counters[key][0] += int(correct)
            predicted_fields.append({"field_name": name, "raw_value": value,
                                     "expected": field["expected_raw"], "correct": correct,
                                     "accepted": False, "engine": "tesseract"})
        predictions.append({"document_id": document_id, "fields": predicted_fields})
    metrics = {key: {"correct": value[0], "total": value[1],
                     "accuracy": value[0] / value[1] if value[1] else 0}
               for key, value in sorted(counters.items())}
    sorted_latency = sorted(latencies)
    metrics["runtime"] = {"calls": len(latencies), "p95_latency_ms": sorted_latency[int(.95 * (len(sorted_latency)-1))],
                          "mean_latency_ms": sum(latencies) / len(latencies)}
    metrics["qualification"] = {"synthetic_only": True, "production_holdout": False,
                                "false_accepts": 0, "note": "accepted=false for all synthetic OCR candidates"}
    (args.output / "predictions.json").write_text(json.dumps({"documents": predictions}, indent=2), "utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), "utf-8")
    print(json.dumps({"overall": metrics["overall"], "runtime": metrics["runtime"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
