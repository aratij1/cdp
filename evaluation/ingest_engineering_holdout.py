"""Audit and register the independent synthetic engineering holdout."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from evaluation.schemas import GroundTruthDataset, GroundTruthDocument, GroundTruthField


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    ROOT / "evaluation_data" / "holdouts" / "PRODUCTION_HOLDOUT_V1_SYNTHETIC"
)
DEFAULT_OUTPUT = (
    ROOT / "evaluation_results" / "production_readiness" /
    "engineering_holdout_v1_synthetic"
)
ARCHIVE_SHA256 = "620efa1b3b0eacb4db90179a0c98f23d5e0ff5c12dffab42fc7d3de1619f9c86"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _form_type(family: str) -> str:
    if family.startswith("CMS1500_LIKE"):
        return "CMS1500"
    if family.startswith("UB04_LIKE"):
        return "UB04"
    return "UNSTRUCTURED"


def _canonical_fields(family: str, fields: dict) -> list[GroundTruthField]:
    if family.startswith("CMS1500_LIKE"):
        mapping = {
            "patient_name": "patient_name",
            "patient_dob": "dob",
            "insured_id_number": "member_id",
            "total_charge": "total_charge",
        }
    elif family.startswith("UB04_LIKE"):
        mapping = {
            "patient_name": "patient_name",
            "patient_dob": "dob",
            "provider_npi": "provider_npi",
            "type_of_bill": "type_of_bill",
            "principal_diagnosis": "principal_diagnosis",
        }
    else:
        mapping = {"document_class": "document_class"}
    return [
        GroundTruthField(
            field_name=canonical,
            expected_raw=fields[source],
            required=True,
            critical=canonical != "document_class",
        )
        for canonical, source in mapping.items()
        if source in fields
    ]


def audit_and_register(
    *, dataset: Path = DEFAULT_DATASET, output: Path = DEFAULT_OUTPUT,
) -> dict:
    manifest = json.loads((dataset / "manifest.json").read_text("utf-8"))
    attestation = json.loads((dataset / "attestation.json").read_text("utf-8"))
    metadata_path = dataset / "metadata" / "document_metadata.jsonl"
    truth_path = dataset / "ground_truth" / "ground_truth.jsonl"
    metadata = _jsonl(metadata_path)
    truth = _jsonl(truth_path)
    with (dataset / "index.csv").open(newline="", encoding="utf-8") as stream:
        index = list(csv.DictReader(stream))

    errors: list[str] = []
    if manifest.get("ground_truth_sha256") != sha256(truth_path):
        errors.append("GROUND_TRUTH_HASH_MISMATCH")
    if manifest.get("metadata_sha256") != sha256(metadata_path):
        errors.append("METADATA_HASH_MISMATCH")
    if not (len(index) == len(metadata) == len(truth) == manifest.get("document_count")):
        errors.append("DOCUMENT_COUNT_MISMATCH")
    ids = {
        "index": [row["document_id"] for row in index],
        "metadata": [row["document_id"] for row in metadata],
        "truth": [row["document_id"] for row in truth],
    }
    if any(len(values) != len(set(values)) for values in ids.values()):
        errors.append("DUPLICATE_DOCUMENT_ID")
    if not (set(ids["index"]) == set(ids["metadata"]) == set(ids["truth"])):
        errors.append("DOCUMENT_ID_SET_MISMATCH")
    document_hashes = set()
    for row in index:
        path = dataset / row["path"]
        actual = sha256(path) if path.is_file() else None
        if actual != row["sha256"]:
            errors.append(f"DOCUMENT_HASH_MISMATCH:{row['document_id']}")
        if actual:
            document_hashes.add(actual)
        if row["synthetic"].lower() != "true" or row["contains_phi"].lower() != "false":
            errors.append(f"CLASSIFICATION_MISMATCH:{row['document_id']}")

    development_hashes = set()
    for root in (ROOT / "dataset_raw", ROOT / "evaluation_data" / "synthetic_public_v3"):
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf"}:
                    development_hashes.add(sha256(path))
    overlap_count = len(document_hashes & development_hashes)
    if overlap_count:
        errors.append("EXACT_DEVELOPMENT_OVERLAP")

    metadata_by_id = {row["document_id"]: row for row in metadata}
    canonical_documents = []
    missing_policy_fields = Counter()
    for row in truth:
        family = row["family"]
        canonical = _canonical_fields(family, row["fields"])
        if family.startswith("UB04_LIKE") and "federal_tax_no" not in row["fields"]:
            missing_policy_fields["UB04.federal_tax_no"] += 1
        canonical_documents.append(GroundTruthDocument(
            document_id=row["document_id"],
            file_name=metadata_by_id[row["document_id"]]["path"],
            form_type=_form_type(family),
            image_quality_bucket=metadata_by_id[row["document_id"]]["quality_bucket"],
            split="holdout",
            fields=canonical,
        ))
    canonical_truth = GroundTruthDataset(documents=canonical_documents)

    output.mkdir(parents=True, exist_ok=True)
    canonical_path = output / "canonical_ground_truth.json"
    canonical_path.write_text(canonical_truth.model_dump_json(indent=2), "utf-8")
    audit = {
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["version"],
        "status": "FROZEN_ENGINEERING_HOLDOUT" if not errors else "REJECTED",
        "synthetic": bool(manifest.get("synthetic")),
        "contains_real_phi": bool(manifest.get("contains_real_phi")),
        "production_promotion_authority": bool(manifest.get("production_promotion_authority")),
        "archive_sha256": ARCHIVE_SHA256,
        "document_count": len(index),
        "canonical_field_observations": sum(len(item.fields) for item in canonical_documents),
        "composition": manifest["composition"],
        "quality_buckets": dict(Counter(row["quality_bucket"] for row in metadata)),
        "exact_development_overlap_count": overlap_count,
        "missing_claim_policy_fields": dict(missing_policy_fields),
        "claim_stp_qualification_complete": not missing_policy_fields,
        "attestation": attestation,
        "errors": errors,
        "tuning_prohibited": True,
        "production_note": (
            "Independent engineering evidence only; cannot alone authorize production promotion."
        ),
        "canonical_ground_truth_sha256": sha256(canonical_path),
    }
    (output / "ingestion_audit.json").write_text(json.dumps(audit, indent=2), "utf-8")
    if errors:
        raise ValueError("engineering holdout audit failed: " + ", ".join(errors[:10]))
    return audit


def main() -> int:
    audit = audit_and_register()
    print(json.dumps({
        key: audit[key] for key in (
            "dataset_id", "status", "document_count",
            "canonical_field_observations", "exact_development_overlap_count",
            "claim_stp_qualification_complete",
        )
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
