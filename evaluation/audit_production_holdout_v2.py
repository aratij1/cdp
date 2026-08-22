"""Integrity and governance audit for the sealed Phase-6 holdout."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation_data/holdouts/PRODUCTION_HOLDOUT_V2_REPRESENTATIVE"
DEFAULT_OUTPUT = ROOT / "evaluation_results/production_holdout_v2"
ARCHIVE_SHA256 = "56af099657cfc79b01789ed89905dcbabb2142e0219097aedc41c5d77a22f0d"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def audit(dataset: Path = DEFAULT_DATASET, output: Path = DEFAULT_OUTPUT) -> dict:
    manifest_path = dataset / "manifest.json"
    metadata_path = dataset / "metadata/document_metadata.jsonl"
    truth_path = dataset / "ground_truth/ground_truth.jsonl"
    required = [manifest_path, dataset / "provenance/attestation.json",
                dataset / "evaluation_contract.json", metadata_path, truth_path]
    missing = [str(path.relative_to(dataset)) for path in required if not path.is_file()]
    if missing:
        raise ValueError(f"missing required holdout files: {missing}")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    metadata, truth = _jsonl(metadata_path), _jsonl(truth_path)
    errors = []
    if sha256(truth_path) != manifest["ground_truth_sha256"]:
        errors.append("GROUND_TRUTH_HASH_MISMATCH")
    if sha256(metadata_path) != manifest["metadata_sha256"]:
        errors.append("METADATA_HASH_MISMATCH")
    if len(metadata) != manifest["document_count"] or len(truth) != manifest["document_count"]:
        errors.append("DOCUMENT_COUNT_MISMATCH")
    metadata_ids = [item["document_id"] for item in metadata]
    truth_ids = [item["document_id"] for item in truth]
    if len(set(metadata_ids)) != len(metadata_ids) or len(set(truth_ids)) != len(truth_ids):
        errors.append("DUPLICATE_DOCUMENT_ID")
    if set(metadata_ids) != set(truth_ids):
        errors.append("DOCUMENT_ID_SET_MISMATCH")
    actual_hashes = []
    for item in metadata:
        path = dataset / item["path"]
        actual = sha256(path) if path.is_file() else None
        if actual != item["sha256"]:
            errors.append(f"DOCUMENT_HASH_MISMATCH:{item['document_id']}")
        if actual:
            actual_hashes.append(actual)
        if item.get("contains_real_phi") or item.get("historical_claim"):
            errors.append(f"PROVENANCE_CLASSIFICATION_MISMATCH:{item['document_id']}")
    duplicate_content = len(actual_hashes) - len(set(actual_hashes))
    if duplicate_content:
        errors.append(f"DUPLICATE_DOCUMENT_CONTENT:{duplicate_content}")
    audit_result = {
        "dataset_id": manifest["dataset_id"], "version": manifest["version"],
        "status": "VERIFIED_FROZEN" if not errors else "REJECTED",
        "archive_sha256": ARCHIVE_SHA256, "document_count": len(metadata),
        "ground_truth_sha256": sha256(truth_path), "metadata_sha256": sha256(metadata_path),
        "family_distribution": dict(Counter(item["family"] for item in metadata)),
        "quality_distribution": dict(Counter(item["quality_bucket"] for item in metadata)),
        "duplicate_document_content": duplicate_content,
        "production_representative": manifest.get("production_representative"),
        "contains_real_phi": manifest.get("contains_real_phi"),
        "tuning_prohibited": manifest.get("tuning_prohibited"),
        "production_authority": "SHADOW_READINESS_ONLY",
        "errors": errors,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "integrity_audit.json").write_text(json.dumps(audit_result, indent=2), "utf-8")
    if errors:
        raise ValueError("holdout integrity audit failed: " + ", ".join(errors[:20]))
    return audit_result


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2))
