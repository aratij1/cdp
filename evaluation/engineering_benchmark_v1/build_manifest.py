from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .contracts import EngineeringBenchmarkManifest, EngineeringBenchmarkRecord


ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = ROOT / "evaluation_results" / "engineering_benchmark_v1"


def _json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _route(family: str, structured_support: bool = False) -> str:
    if family == "CMS1500":
        return "CMS_STANDARD_EXTRACTOR"
    if family == "UB04":
        return "UB_STANDARD_EXTRACTOR"
    if family in {"CUSTOM_PROFESSIONAL", "CUSTOM_INSTITUTIONAL", "UNKNOWN_STRUCTURED"}:
        return "LAYOUT_STRUCTURED_EXTRACTOR"
    if family == "CLAIM_SUPPORT":
        return "LAYOUT_STRUCTURED_EXTRACTOR" if structured_support else "UNSTRUCTURED_EXTRACTOR"
    if family == "NON_CLAIM":
        return "STOP_NON_CLAIM"
    return "UNSTRUCTURED_EXTRACTOR"


def _record(*, source: str, document_id: str, family: str, image: Path,
            quality: str = "unknown", failure: str | None = None,
            fields: dict[str, Any] | None = None,
            crops: dict[str, Iterable[int]] | None = None,
            tuning_allowed: bool = False, structured_support: bool = False,
            expected_sha: str | None = None) -> EngineeringBenchmarkRecord:
    if not image.is_file():
        raise FileNotFoundError(image)
    actual_sha = _sha(image)
    if expected_sha and actual_sha != expected_sha:
        raise ValueError(f"SHA mismatch for {image}: {actual_sha} != {expected_sha}")
    relative = image.resolve().relative_to(ROOT.resolve()).as_posix()
    return EngineeringBenchmarkRecord(
        document_id=f"{source}:{document_id}", page_id="1", expected_family=family,
        expected_processing_route=_route(family, structured_support),
        source_dataset=source, synthetic_or_test=True, image_path=relative,
        sha256=actual_sha, quality_bucket=(quality or "unknown"),
        failure_bucket=failure, truth_fields=fields or {},
        crop_boxes={key: tuple(value) for key, value in (crops or {}).items()},
        tuning_allowed=tuning_allowed,
    )


def _public_synthetic(version: int) -> list[EngineeringBenchmarkRecord]:
    source = f"SYNTHETIC_PUBLIC_V{version}"
    base = ROOT / "evaluation_data" / f"synthetic_public_v{version}"
    truth = _json(base / "ground_truth.json")["documents"]
    geometry = _json(base / "document_manifest.json")
    records = []
    for row in truth:
        manifest = geometry[row["document_id"]]
        fields = {item["field_name"]: item.get("expected_normalized") or item["expected_raw"]
                  for item in row.get("fields", [])}
        family = "CMS1500" if row["form_type"].startswith("CMS") else "UB04"
        records.append(_record(source=source, document_id=row["document_id"], family=family,
            image=base / row["file_name"], quality=row.get("image_quality_bucket", "unknown"),
            fields=fields, crops=manifest.get("crop_boxes"), tuning_allowed=False))
    return records


def _routing_dev(version: int) -> list[EngineeringBenchmarkRecord]:
    source = f"ROUTING_DEV_V{version}"
    base = ROOT / "evaluation_data" / source
    mapping = {
        "CMS1500": ("CMS1500", False), "UB04": ("UB04", False),
        "CUSTOM_STRUCTURED": ("CUSTOM_PROFESSIONAL", False),
        "UNKNOWN_STRUCTURED": ("UNKNOWN_STRUCTURED", False),
        "ATTACHMENT": ("CLAIM_SUPPORT", False),
        "UNKNOWN_UNSTRUCTURED": ("UNKNOWN_UNSTRUCTURED", False),
        "NON_CLAIM": ("NON_CLAIM", False),
    }
    records = []
    for row in _jsonl(base / "ground_truth.jsonl"):
        family, structured_support = mapping[row["truth_route"]]
        records.append(_record(source=source, document_id=row["document_id"], family=family,
            image=base / row["path"], quality=row.get("quality_bucket") or row.get("condition", "unknown"),
            tuning_allowed=True, structured_support=structured_support))
    return records


def _bundle_d() -> list[EngineeringBenchmarkRecord]:
    source = "BUNDLE_D_DEV_V1"
    base = ROOT / "evaluation_data" / "bundle_d_dev_v1"
    custom = {
        "PROFESSIONAL_CLAIM_LIKE": "CUSTOM_PROFESSIONAL",
        "INSTITUTIONAL_CLAIM_LIKE": "CUSTOM_INSTITUTIONAL",
    }
    structured_support = {"EOB", "ITEMIZED_BILL", "MEDICAL_INVOICE", "LAB_REPORT", "PROVIDER_STATEMENT"}
    records = []
    for row in _jsonl(base / "ground_truth.jsonl"):
        raw_family = row["family"]
        if raw_family in custom:
            family, structured = custom[raw_family], False
        elif raw_family in {"NON_CLAIM", "NONCLAIM"}:
            family, structured = "NON_CLAIM", False
        else:
            family, structured = "CLAIM_SUPPORT", raw_family in structured_support
        records.append(_record(source=source, document_id=row["document_id"], family=family,
            image=base / row["path"], quality="clean", fields=row.get("fields"),
            tuning_allowed=True, structured_support=structured))
    return records


def _remediation() -> list[EngineeringBenchmarkRecord]:
    source = "ROUTING_DEV_V4_REMEDIATION_01"
    base = ROOT / "evaluation_results" / "router_v4" / "remediation_01"
    result = []
    for row in _json(base / "manifest.json")["documents"]:
        raw = row["truth"]
        family = {"CUSTOM_STRUCTURED": "CUSTOM_PROFESSIONAL"}.get(raw, raw)
        result.append(_record(source=source, document_id=row["document_id"], family=family,
            image=base / row["file"], quality=row.get("quality_bucket", "REMEDIATION"),
            failure=row.get("failure_bucket"), tuning_allowed=True,
            expected_sha=row.get("sha256")))
    return result


def _representative_v2() -> list[EngineeringBenchmarkRecord]:
    source = "PRODUCTION_HOLDOUT_V2_REPRESENTATIVE"
    base = ROOT / "evaluation_data" / "holdouts" / source
    truth = {row["document_id"]: row for row in _jsonl(base / "ground_truth" / "ground_truth.jsonl")}
    mapping = {
        "CMS1500_0212": ("CMS1500", False),
        "UB04_CMS1450_COMPAT": ("UB04", False),
        "CUSTOM_PROFESSIONAL_CLAIM": ("CUSTOM_PROFESSIONAL", False),
        "CLAIM_ATTACHMENT": ("CLAIM_SUPPORT", False),
        "NON_CLAIM": ("NON_CLAIM", False),
    }
    records = []
    for meta in _jsonl(base / "metadata" / "document_metadata.jsonl"):
        family, structured = mapping[meta["family"]]
        truth_row = truth[meta["document_id"]]
        records.append(_record(source=source, document_id=meta["document_id"], family=family,
            image=base / meta["path"], quality=meta.get("quality_bucket", "unknown"),
            fields=truth_row.get("fields"), tuning_allowed=False,
            structured_support=structured, expected_sha=meta.get("sha256")))
    return records


def build_manifest(output_dir: Path = RESULT_ROOT) -> EngineeringBenchmarkManifest:
    candidates: list[EngineeringBenchmarkRecord] = []
    for version in (1, 2, 3):
        candidates.extend(_public_synthetic(version))
    candidates.extend(_routing_dev(2))
    candidates.extend(_routing_dev(3))
    candidates.extend(_bundle_d())
    candidates.extend(_remediation())
    candidates.extend(_representative_v2())

    # Exact pixel duplicates can bias both accuracy and latency. Preserve the
    # first allowlisted occurrence and disclose every removal.
    unique: list[EngineeringBenchmarkRecord] = []
    seen: dict[str, str] = {}
    duplicates = []
    for record in candidates:
        if record.sha256 in seen:
            duplicates.append({"excluded": record.document_id, "duplicate_of": seen[record.sha256],
                               "sha256": record.sha256})
            continue
        seen[record.sha256] = record.document_id
        unique.append(record)

    payload = [record.model_dump(mode="json") for record in unique]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = EngineeringBenchmarkManifest(records=unique, record_count=len(unique), manifest_sha256=digest)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), "utf-8")
    inventory = {
        "evidence_class": manifest.evidence_class,
        "production_promotion_authority": False,
        "candidate_count": len(candidates), "unique_count": len(unique),
        "duplicates_removed": duplicates,
        "family_counts": dict(sorted(Counter(row.expected_family for row in unique).items())),
        "source_counts": dict(sorted(Counter(row.source_dataset for row in unique).items())),
        "quality_counts": dict(sorted(Counter(row.quality_bucket for row in unique).items())),
        "tuning_allowed_count": sum(row.tuning_allowed for row in unique),
        "observation_only_count": sum(not row.tuning_allowed for row in unique),
    }
    (output_dir / "inventory.json").write_text(json.dumps(inventory, indent=2), "utf-8")
    return manifest


if __name__ == "__main__":
    built = build_manifest()
    print(json.dumps({"records": built.record_count, "sha256": built.manifest_sha256,
                      "evidence_class": built.evidence_class}, indent=2))
