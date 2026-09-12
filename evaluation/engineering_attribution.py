"""Private causal review after engineering truth is frozen; never edit source labels."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from evaluation.engineering_review import SCOPE, content_hash, directory, read_manifest
from evaluation.qualification_state import immutable_json

CAUSES = {"TRUE_SOURCE_INVALID", "OCR_RECOGNITION_ERROR", "OCR_LOCALIZATION_ERROR", "NORMALIZATION_ERROR",
          "VALIDATOR_FALSE_REJECT", "VALIDATOR_TRUE_REJECT", "LABEL_CONTAMINATION", "SOURCE_UNREADABLE",
          "REFERENCE_REQUIRED", "OTHER"}


def record(field_id: str, cause: str, reviewer: str, evidence_reference: str) -> None:
    path=directory()/"engineering_truth.json"
    if not path.exists(): raise ValueError("FREEZE_SOURCE_ONLY_TRUTH_BEFORE_CAUSAL_REVIEW")
    truth=json.loads(path.read_text(encoding="utf-8"))
    seal=truth.pop("truth_sha256")
    manifest=read_manifest()
    if content_hash(truth)!=seal or truth.get("manifest_sha256")!=manifest["manifest_sha256"]:
        raise ValueError("ENGINEERING_TRUTH_CHANGED")
    if (field_id not in {row["field_id"] for row in manifest["fields"]} or cause not in CAUSES
            or not reviewer.strip() or not evidence_reference.strip()):
        raise ValueError("CAUSAL_REVIEW_PROVENANCE_REQUIRED")
    payload={"scope":SCOPE,"production_authority":False,"field_id":field_id,"root_cause":cause,
             "reviewer_reference":reviewer,"evidence_reference":evidence_reference,
             "reviewed_at":datetime.now(UTC).isoformat(),"truth_sha256":seal,
             "saved_ocr_sha256":manifest["saved_ocr_sha256"]}
    payload["provenance_sha256"]=content_hash(payload)
    immutable_json(directory()/"attributions"/(field_id+".json"),payload)


def read(field_id: str, truth_sha256: str, saved_ocr_sha256: str) -> str | None:
    path=directory()/"attributions"/(field_id+".json")
    if not path.exists(): return None
    row=json.loads(path.read_text(encoding="utf-8"));seal=row.pop("provenance_sha256")
    if (content_hash(row)!=seal or row.get("truth_sha256")!=truth_sha256 or row.get("saved_ocr_sha256")!=saved_ocr_sha256
            or row.get("field_id")!=field_id or row.get("root_cause") not in CAUSES):
        raise ValueError("CAUSAL_REVIEW_BINDING_CHANGED")
    return row["root_cause"]


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--file",type=Path,required=True)
    parser.add_argument("--reviewer-reference",required=True);args=parser.parse_args()
    try:
        rows=json.loads(args.file.read_text(encoding="utf-8"))
        for row in rows: record(row["field_id"],row["root_cause"],args.reviewer_reference,row["evidence_reference"])
    except (ValueError,OSError,KeyError,TypeError): raise SystemExit("CAUSAL_REVIEW_IMPORT_REJECTED") from None
    print(json.dumps({"scope":SCOPE,"attributions_recorded":len(rows),"production_authority":False}))
