"""Select opaque field metadata only; predictions never enter the review manifest."""
from __future__ import annotations

import json
from pathlib import Path

from evaluation.engineering_review import SCOPE, content_hash, digest, directory
from evaluation.qualification_state import immutable_json
from packages.runtime_policy_coverage import supported_runtime_fields


def prepare(saved: Path) -> dict:
    raw_path = saved/"raw_execution.local.json"
    before = digest(raw_path)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    inputs = json.loads((saved/"execution_input.local.json").read_text(encoding="utf-8"))
    sources = {row["claim_alias"]:row for row in inputs["claims"]}
    allowed = set().union(*supported_runtime_fields().values())
    rows = []
    for claim in raw["claims"]:
        source = sources[claim["claim_alias"]]
        path = Path(source["source_path"]).resolve()
        if digest(path) != claim["source_sha256"] or source["source_sha256"] != claim["source_sha256"]:
            raise ValueError("ENGINEERING_SOURCE_BINDING_MISMATCH")
        pages = {p["page_number"]:p["page_id"] for p in claim["pages"]}
        for field in claim["fields"]:
            if field["field_name"] not in allowed: raise ValueError("UNSUPPORTED_ENGINEERING_FIELD")
            # Deliberate allowlist: no values, candidates, confidence, or OCR bounding boxes.
            rows.append({"field_id":content_hash({"field_id":field["field_id"]}),
                         "scan_id":content_hash({"document_id":claim["document_id"]}),
                         "page_id":content_hash({"page_id":pages[field["page_number"]]}),
                         "field_name":field["field_name"], "frame":field["page_number"]-1,
                         "source_path":str(path), "source_sha256":claim["source_sha256"]})
    if len(raw["claims"])!=12 or len(rows)!=21 or len({r["field_id"] for r in rows})!=21:
        raise ValueError("EXACT_12_SCAN_21_FIELD_COHORT_REQUIRED")
    manifest = {"scope":SCOPE,"production_authority":False,"scans":12,"fields":rows,
                "saved_ocr_sha256":before,"normalization":"EXACT_ONLY_NO_NEW_NORMALIZATION_APPROVED"}
    manifest["manifest_sha256"] = content_hash(manifest)
    immutable_json(directory()/"source_manifest.json",manifest)
    if digest(raw_path)!=before: raise ValueError("SAVED_OCR_CHANGED")
    return {"scope":SCOPE,"fields":21,"scans":12,"ocr_calls":0,"labels_prefilled":0}


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--saved",type=Path,required=True)
    args=parser.parse_args()
    try: result=prepare(args.saved)
    except (ValueError,OSError,KeyError): raise SystemExit("ENGINEERING_INTAKE_FAILED_CHECK_MOUNT_AND_BINDINGS") from None
    print(json.dumps(result))
