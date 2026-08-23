"""Build the deterministic, tuning-only Phase 7A.15 annotation queue.

This command creates annotation tasks and empty verified-truth streams. It never
promotes model output or a template ROI to human truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from evaluation.engineering_benchmark_v1.freeze import load_frozen_manifest
from evaluation.tuning_truth.schema import FIELDS_BY_FAMILY

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluation_results" / "phase7a15"
SEED = 7152026
TARGETS = {"CMS1500": 110, "UB04": 110, "CUSTOM": 30}
CUSTOM_FAMILIES = {"CUSTOM_PROFESSIONAL", "CUSTOM_INSTITUTIONAL"}


def _stable_rank(seed: int, *values: object) -> str:
    payload = "|".join((str(seed), *(str(value) for value in values)))
    return hashlib.sha256(payload.encode()).hexdigest()


def _allocate(groups: dict[tuple[str, str], list[Any]], target: int) -> dict[tuple[str, str], int]:
    total = sum(len(rows) for rows in groups.values())
    if target >= total:
        return {key: len(rows) for key, rows in groups.items()}
    raw = {key: target * len(rows) / total for key, rows in groups.items()}
    allocation = {key: min(len(groups[key]), math.floor(value)) for key, value in raw.items()}
    remaining = target - sum(allocation.values())
    order = sorted(groups, key=lambda key: (-(raw[key] - allocation[key]), key))
    for key in order:
        if not remaining:
            break
        if allocation[key] < len(groups[key]):
            allocation[key] += 1
            remaining -= 1
    return allocation


def stratified_select(records: Iterable[Any], target: int, seed: int) -> list[Any]:
    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in records:
        groups[(row.source_dataset, row.quality_bucket)].append(row)
    allocation = _allocate(groups, target)
    selected = []
    for key in sorted(groups):
        ranked = sorted(groups[key], key=lambda row: _stable_rank(seed, row.document_id, row.page_id))
        selected.extend(ranked[: allocation[key]])
    return sorted(selected, key=lambda row: (row.expected_family, row.document_id, row.page_id))


def _sha(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )


def build(output: Path = DEFAULT_OUTPUT, seed: int = SEED) -> dict:
    manifest = load_frozen_manifest()
    tuning = [row for row in manifest.records if row.tuning_allowed]
    if len(tuning) != 430 or any(not row.tuning_allowed for row in tuning):
        raise ValueError("frozen 430-page tuning boundary is not intact")

    cms = [row for row in tuning if row.expected_family == "CMS1500"]
    ub = [row for row in tuning if row.expected_family == "UB04"]
    custom = [row for row in tuning if row.expected_family in CUSTOM_FAMILIES]
    selected = (
        stratified_select(cms, TARGETS["CMS1500"], seed)
        + stratified_select(ub, TARGETS["UB04"], seed)
        + stratified_select(custom, TARGETS["CUSTOM"], seed)
    )
    if len(selected) != 250 or len({row.document_id for row in selected}) != 250:
        raise ValueError("annotation selection must contain 250 unique pages")

    forensic_path = ROOT / "evaluation_results/phase7a14b/registration_forensics.json"
    forensic = json.loads(forensic_path.read_text("utf-8")) if forensic_path.is_file() else {}
    attempts = {row["document_id"]: row for row in forensic.get("attempts", [])}
    records = []
    tasks = []
    for row in selected:
        attempt = attempts.get(row.document_id, {})
        item = {
            "document_id": row.document_id,
            "page_id": row.page_id,
            "form_family": row.expected_family,
            "source_dataset": row.source_dataset,
            "quality_bucket": row.quality_bucket,
            "image_path": row.image_path,
            "image_sha256": row.sha256,
            "geometry_mode": "UNAVAILABLE",
            "template_compatibility": attempt.get("compatibility_status", "UNAVAILABLE"),
            "registration_failure": attempt.get("failure_reason"),
            "tuning_status": "TUNING_PERMITTED",
        }
        records.append(item)
        for field_name in FIELDS_BY_FAMILY[row.expected_family]:
            tasks.append({
                **item,
                "task_type": "FIELD_AND_CROP",
                "field_name": field_name,
                "review_status": "UNVERIFIED",
                "preannotation": None,
            })

    ub_selected = [row for row in records if row["form_family"] == "UB04"]
    ub_line_pages = sorted(
        ub_selected, key=lambda row: _stable_rank(seed, "UB_LINES", row["document_id"])
    )[:50]
    for row in ub_line_pages:
        tasks.append({
            **row,
            "task_type": "UB_SERVICE_LINES",
            "review_status": "UNVERIFIED",
            "preannotation": None,
        })

    canonical_selection = [
        {key: row[key] for key in ("document_id", "page_id", "image_sha256")} for row in records
    ]
    selection_hash = _sha(canonical_selection)
    output.mkdir(parents=True, exist_ok=True)
    sample = {
        "dataset_id": "TUNING_TRUTH_V1_STAGING",
        "status": "ANNOTATION_IN_PROGRESS",
        "source_manifest_sha256": manifest.manifest_sha256,
        "random_seed": seed,
        "selection_rules": {
            "eligible_split": "TUNING_PERMITTED_ONLY",
            "strata": ["form_family", "source_dataset", "quality_bucket"],
            "within_stratum_order": "SHA256(seed|document_id|page_id)",
            "targets": TARGETS,
            "no_easy_document_filter": True,
        },
        "page_count": len(records),
        "family_distribution": dict(sorted(Counter(row["form_family"] for row in records).items())),
        "source_distribution": dict(sorted(Counter(row["source_dataset"] for row in records).items())),
        "quality_distribution": dict(sorted(Counter(row["quality_bucket"] for row in records).items())),
        "service_line_annotation_page_target": len(ub_line_pages),
        "selection_sha256": selection_hash,
        "observation_only_pages_selected": 0,
        "records": records,
    }
    _write_json(output / "annotation_sample_manifest.json", sample)
    _write_jsonl(output / "annotation_tasks.jsonl", tasks)
    # Truth streams remain empty until a reviewer explicitly verifies annotations.
    for name in ("field_truth.jsonl", "crop_truth.jsonl", "ub_service_line_truth.jsonl"):
        _write_jsonl(output / name, [])
    _write_json(output / "annotation_quality.json", {
        "status": "NOT_RUN_NO_VERIFIED_TRUTH", "errors": [], "warnings": [],
    })
    _write_json(output / "dataset_freeze.json", {
        "dataset_id": "TUNING_TRUTH_V1",
        "frozen": False,
        "status": "BLOCKED_PENDING_HUMAN_VERIFICATION",
        "selection_sha256": selection_hash,
        "verified_field_records": 0,
        "verified_crop_records": 0,
        "verified_service_line_pages": 0,
    })
    return sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    result = build(args.output, args.seed)
    print(json.dumps({key: result[key] for key in (
        "page_count", "family_distribution", "selection_sha256",
        "observation_only_pages_selected",
    )}, indent=2))


if __name__ == "__main__":
    main()
