"""Write an immutable-content audit for a generated Bundle-D corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from evaluation.generate_bundle_d_dev_v1 import DEFAULT_UNTOUCHED


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze(dataset: Path) -> dict:
    manifest = json.loads((dataset / "manifest.json").read_text("utf-8"))
    if not manifest.get("frozen_holdout") or not manifest.get("tuning_prohibited"):
        raise ValueError("only a tuning-prohibited holdout can be frozen")
    truth_path = dataset / "ground_truth.jsonl"
    truth = [json.loads(line) for line in truth_path.read_text("utf-8").splitlines()]
    document_hashes = {item["document_id"]: _hash(dataset / item["path"]) for item in truth}
    duplicates = len(document_hashes) - len(set(document_hashes.values()))
    if duplicates:
        (dataset / "freeze_audit.json").write_text(json.dumps({
            "dataset_id": manifest["dataset_id"], "status": "REJECTED_DUPLICATES",
            "document_count": len(truth), "duplicate_document_count": duplicates,
            "tuning_prohibited": True,
        }, indent=2), "utf-8")
        raise ValueError(f"holdout contains {duplicates} byte-identical duplicate documents")
    audit = {
        "dataset_id": manifest["dataset_id"], "status": "FROZEN",
        "document_count": len(truth), "ground_truth_sha256": _hash(truth_path),
        "manifest_sha256": _hash(dataset / "manifest.json"),
        "document_sha256": document_hashes,
        "duplicate_document_count": 0,
        "tuning_prohibited": True,
    }
    (dataset / "freeze_audit.json").write_text(json.dumps(audit, indent=2), "utf-8")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--dataset", type=Path, default=DEFAULT_UNTOUCHED)
    args = parser.parse_args(); print(json.dumps(freeze(args.dataset), indent=2))
