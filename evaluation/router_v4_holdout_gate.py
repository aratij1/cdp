"""Validate external holdout provenance before any document can reach Router V4."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
REQUIRED={"dataset_id","source","source_owner","creation_or_acquisition_date","document_count","family_distribution","quality_distribution","documents_sha256","ground_truth_hash","phi_exists","authorization_status","development_non_use_attestation","freeze_status"}
def validate_holdout(manifest_path:Path,candidate_path:Path)->dict:
    if not candidate_path.is_file(): return {"decision":"NEEDS_MORE_DATA","reason":"ROUTER_V4_CANDIDATE_1_DOES_NOT_EXIST","routing_permitted":False}
    if not manifest_path.is_file(): return {"decision":"NEEDS_MORE_DATA","reason":"EXTERNAL_HOLDOUT_PROVENANCE_MISSING","routing_permitted":False}
    value=json.loads(manifest_path.read_text("utf-8")); missing=sorted(REQUIRED-set(value))
    if missing:return {"decision":"NEEDS_MORE_DATA","reason":"PROVENANCE_FIELDS_MISSING","missing":missing,"routing_permitted":False}
    if value["freeze_status"]!="FROZEN_UNTOUCHED" or not value["development_non_use_attestation"]:return {"decision":"REJECT","reason":"HOLDOUT_NOT_UNTOUCHED","routing_permitted":False}
    return {"decision":"ELIGIBLE_FOR_ONE_SHOT_ROUTING","manifest_hash":hashlib.sha256(manifest_path.read_bytes()).hexdigest(),"routing_permitted":True}

