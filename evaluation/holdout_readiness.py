"""Create a truthful, machine-readable PRODUCTION_HOLDOUT_V1 readiness record."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evaluation.untouched_holdout import REQUIRED_CONDITIONS


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "production_holdout_policy.yaml"
MANIFEST_PATH = ROOT / "evaluation" / "holdout" / "manifest.json"
READINESS_PATH = (
    ROOT / "evaluation_results" / "production_readiness" / "holdout_readiness.json"
)


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def build_readiness_record(
    *, manifest_path: Path = MANIFEST_PATH,
    readiness_path: Path = READINESS_PATH,
) -> dict:
    policy = yaml.safe_load(POLICY_PATH.read_text("utf-8"))
    record = {
        "schema_version": "production-holdout-readiness-v1",
        "dataset_id": policy["dataset_id"],
        "dataset_version": "PRODUCTION_HOLDOUT_V1",
        "status": "NEEDS_MORE_DATA",
        "freeze_status": "NOT_FROZEN",
        "eligible_for_evaluation": False,
        "eligible_for_promotion": False,
        "created_at": datetime.now(UTC).isoformat(),
        "source_description": "No independent external source has been provided.",
        "asset_count": 0,
        "page_count": 0,
        "field_observation_count": 0,
        "assets": [],
        "document_sha256": [],
        "page_sha256": [],
        "ground_truth_hashes": [],
        "attestation": None,
        "sample_targets": {
            key: value for key, value in policy.items()
            if key.startswith("minimum_")
        },
        "required_conditions": sorted(REQUIRED_CONDITIONS),
        "rejected_repository_sources": [
            {
                "path": "dataset_raw/",
                "reason": "INSPECTED_DEVELOPMENT_DATA_USED_BY_PRIOR_EVALUATION",
            },
            {
                "path": "evaluation_data/",
                "reason": "SYNTHETIC_OR_DEVELOPMENT_EVALUATION_DATA",
            },
            {
                "path": "evaluation_results/",
                "reason": "DERIVED_DEVELOPMENT_OUTPUTS",
            },
        ],
        "eligibility_reasons": [
            "NO_INDEPENDENT_EXTERNAL_SOURCE",
            "NO_DATA_OWNER_ATTESTATION",
            "INSUFFICIENT_DOCUMENTS",
            "INSUFFICIENT_PAGES",
            "INSUFFICIENT_FIELDS",
            "MISSING_DOCUMENT_FAMILY_SAMPLE",
            "MISSING_FIELD_SAMPLE",
            "MISSING_CRITICALITY_SAMPLE",
            "MISSING_IMAGE_QUALITY_SAMPLE",
            "MISSING_COMPOSITION_CONDITIONS",
        ],
        "prohibited_uses": [
            "OCR_SELECTION", "THRESHOLD_TUNING", "ROI_TUNING",
            "REGISTRATION_TUNING", "PREPROCESSING_TUNING", "POLICY_TUNING",
            "BLOCKING_FIELD_TUNING", "ROUTE_SELECTION", "CONFIDENCE_CALIBRATION",
            "PROMPT_TUNING", "REFERENCE_MATCHING_TUNING",
        ],
        "next_action": (
            "Data governance must supply independently sourced assets, truth, hashes, "
            "and a complete untouched-use attestation. Do not tune after unsealing."
        ),
    }
    record["readiness_record_sha256"] = _digest(record)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    readiness_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(record, indent=2)
    manifest_path.write_text(serialized, encoding="utf-8")
    readiness_path.write_text(serialized, encoding="utf-8")
    return record


def main() -> int:
    record = build_readiness_record()
    print(json.dumps({
        "dataset_id": record["dataset_id"],
        "status": record["status"],
        "eligible_for_evaluation": record["eligible_for_evaluation"],
        "asset_count": record["asset_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
