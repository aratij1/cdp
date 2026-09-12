"""Source-only engineering labels. This module never loads OCR prediction values."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from evaluation.qualification_state import immutable_json, initialize_layout

SCOPE = "FRESH_12_ENGINEERING_ONLY"
STATES = {"VALUE", "BLANK", "NOT_PRESENT", "UNREADABLE", "SOURCE_CONFLICT", "NOT_APPLICABLE"}
CAUSES = {"UNDETERMINED", "OCR_RECOGNITION_ERROR", "OCR_LOCALIZATION_ERROR", "NORMALIZATION_ERROR",
          "LABEL_CONTAMINATION", "REFERENCE_REQUIRED", "OTHER"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",", ":")).encode()).hexdigest()


def directory() -> Path:
    path = initialize_layout()/"engineering"/"fresh_12"
    path.mkdir(exist_ok=True)
    return path


def read_manifest() -> dict:
    path = directory()/"source_manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    seal = data.pop("manifest_sha256")
    if content_hash(data) != seal or data.get("scope") != SCOPE or data.get("production_authority") is not False:
        raise ValueError("ENGINEERING_SOURCE_MANIFEST_CHANGED")
    return {**data, "manifest_sha256":seal}


def source_item(field_id: str) -> dict:
    manifest = read_manifest()
    item = next((row for row in manifest["fields"] if row["field_id"] == field_id), None)
    if item is None: raise ValueError("UNKNOWN_REVIEW_FIELD")
    if digest(Path(item["source_path"])) != item["source_sha256"]:
        raise ValueError("REVIEW_SOURCE_CHANGED")
    return item


def save_label(field_id: str, payload: dict, reviewer: str) -> None:
    if (directory()/"engineering_truth.json").exists(): raise ValueError("ENGINEERING_TRUTH_ALREADY_FROZEN")
    item = source_item(field_id)
    if not reviewer.strip() or payload.get("source_only_attested") is not True:
        raise ValueError("SOURCE_ONLY_REVIEW_ATTESTATION_REQUIRED")
    state = payload.get("state")
    value = payload.get("value")
    if state not in STATES or (state == "VALUE" and (not isinstance(value,str) or not value.strip())):
        raise ValueError("SOURCE_STATE_AND_VALUE_REQUIRED")
    if state != "VALUE" and value not in (None, ""):
        raise ValueError("NON_VALUE_STATE_CANNOT_CARRY_VALUE")
    box = payload.get("source_region")
    if (not isinstance(box,list) or len(box)!=4 or not all(type(v) in {int,float} and math.isfinite(v) for v in box)
            or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)):
        raise ValueError("NORMALIZED_SOURCE_REGION_REQUIRED")
    validity = payload.get("source_validity", "UNKNOWN")
    if validity not in {"VALID", "INVALID", "UNKNOWN"}: raise ValueError("INVALID_SOURCE_VALIDITY_STATE")
    label = {"scope":SCOPE, "production_authority":False, "field_id":field_id,
             "scan_id":item["scan_id"], "page_id":item["page_id"], "field_name":item["field_name"],
             "state":state, "value":value if state=="VALUE" else None, "source_region":box,
             "source_validity":validity, "reviewed_at":datetime.now(UTC).isoformat(),
             "reviewer_reference":reviewer, "source_only_attested":True,
             "source_sha256":item["source_sha256"], "manifest_sha256":read_manifest()["manifest_sha256"]}
    label["provenance_sha256"] = content_hash(label)
    immutable_json(directory()/"labels"/(field_id+".json"),label)


def labels() -> list[dict]:
    manifest = read_manifest()
    result = []
    for item in manifest["fields"]:
        path = directory()/"labels"/(item["field_id"]+".json")
        if not path.exists(): continue
        label = json.loads(path.read_text(encoding="utf-8"))
        seal = label.pop("provenance_sha256")
        if (content_hash(label) != seal or label.get("field_id") != item["field_id"]
                or label.get("manifest_sha256") != manifest["manifest_sha256"]
                or label.get("source_sha256") != source_item(item["field_id"])["source_sha256"]):
            raise ValueError("ENGINEERING_LABEL_PROVENANCE_CHANGED")
        result.append({**label,"provenance_sha256":seal})
    return result


def freeze() -> dict:
    manifest = read_manifest()
    rows = labels()
    if len(rows)!=21 or len(manifest["fields"])!=21:
        raise ValueError("ALL_21_SOURCE_LABELS_REQUIRED")
    truth = {"scope":SCOPE,"truth_kind":"ENGINEERING_DIAGNOSTIC_TRUTH", "production_authority":False,
             "manifest_sha256":manifest["manifest_sha256"], "records":rows}
    truth["truth_sha256"] = content_hash(truth)
    immutable_json(directory()/"engineering_truth.json",truth)
    return truth
