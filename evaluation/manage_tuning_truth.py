"""Validate and immutably freeze the human-verified Phase 7A.15 tuning corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from evaluation.tuning_truth.contracts import FieldCropTruth, FieldTruth, UB04ServiceLineTruth
from evaluation.tuning_truth.quality import validate_dataset

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation_results/phase7a15"
DATASET = ROOT / "evaluation/datasets/tuning_truth_v1"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(results: Path = RESULTS) -> dict:
    fields = [FieldTruth.model_validate(row) for row in _rows(results / "field_truth.jsonl")]
    crops = [FieldCropTruth.model_validate(row) for row in _rows(results / "crop_truth.jsonl")]
    lines = [UB04ServiceLineTruth.model_validate(row) for row in _rows(results / "ub_service_line_truth.jsonl")]
    report = validate_dataset(fields, crops, lines)
    (results / "annotation_quality.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


def freeze(results: Path = RESULTS, dataset: Path = DATASET) -> dict:
    freeze_path = results / "dataset_freeze.json"
    existing = json.loads(freeze_path.read_text("utf-8")) if freeze_path.is_file() else {}
    if existing.get("frozen"):
        raise ValueError("TUNING_TRUTH_V1 is already frozen; corrections require V2")
    report = validate(results)
    if report["status"] != "PASS":
        raise ValueError("annotation quality checks failed")
    tasks = _rows(results / "annotation_tasks.jsonl")
    fields = _rows(results / "field_truth.jsonl")
    crops = _rows(results / "crop_truth.jsonl")
    lines = _rows(results / "ub_service_line_truth.jsonl")
    field_keys = {(row["document_id"], row["page_id"], row["field_name"]) for row in fields}
    crop_keys = {(row["document_id"], row["page_id"], row["field_name"]) for row in crops}
    line_keys = {(row["document_id"], row["page_id"]) for row in lines}
    incomplete = []
    for task in tasks:
        if task["task_type"] == "FIELD_AND_CROP":
            key = (task["document_id"], task["page_id"], task["field_name"])
            if key not in field_keys or key not in crop_keys:
                incomplete.append(key)
        elif (task["document_id"], task["page_id"]) not in line_keys:
            incomplete.append((task["document_id"], task["page_id"], "UB_SERVICE_LINES"))
    if incomplete:
        raise ValueError(f"cannot freeze: {len(incomplete)} annotation tasks remain incomplete")
    dataset.mkdir(parents=True, exist_ok=False)
    names = (
        "annotation_sample_manifest.json", "field_truth.jsonl", "crop_truth.jsonl",
        "ub_service_line_truth.jsonl", "annotation_quality.json",
    )
    for name in names:
        shutil.copyfile(results / name, dataset / name)
    payload = {
        "dataset_id": "TUNING_TRUTH_V1",
        "annotation_version": "1",
        "frozen": True,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "selection_sha256": json.loads((results / names[0]).read_text("utf-8"))["selection_sha256"],
        "artifact_sha256": {name: _sha(dataset / name) for name in names},
        "truth_sha256": hashlib.sha256("".join(
            _sha(dataset / name) for name in names[1:4]
        ).encode()).hexdigest(),
        "verified_field_records": len(fields),
        "verified_crop_records": len(crops),
        "verified_service_line_pages": len(lines),
        "correction_policy": "CREATE_TUNING_TRUTH_V2",
    }
    (dataset / "dataset_freeze.json").write_text(json.dumps(payload, indent=2) + "\n", "utf-8")
    freeze_path.write_text(json.dumps(payload, indent=2) + "\n", "utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("validate", "freeze"))
    args = parser.parse_args()
    result = validate() if args.action == "validate" else freeze()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
