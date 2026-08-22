"""Create the immutable Router V3 freeze manifest from validated artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"config/document_routing.yaml"
DATA=ROOT/"evaluation_data/ROUTING_DEV_V3"
BENCHMARK=ROOT/"evaluation_results/ROUTING_DEV_V3/benchmark.json"
OUTPUT=ROOT/"config/router_v3_freeze.json"


def _sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(root:Path)->str:
    digest=hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode()); digest.update(b"\0")
        digest.update(bytes.fromhex(_sha(path)))
    return digest.hexdigest()


def freeze(router_git_sha:str|None=None, output:Path=OUTPUT)->dict:
    cfg=yaml.safe_load(CONFIG.read_text("utf-8"))
    git_sha=router_git_sha or subprocess.check_output(
        ["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    benchmark=json.loads(BENCHMARK.read_text("utf-8"))
    manifest={"freeze_id":"ROUTER_V3","frozen_at":datetime.now(UTC).isoformat(),
        "router_git_sha":git_sha,"router_config_sha256":_sha(CONFIG),
        "anchor_policy_version":cfg["anchor_policy_version"],
        "zone_policy_version":cfg["zone_policy_version"],
        "fuzzy_match_policy_version":cfg["fuzzy_match_policy_version"],
        "structure_model_version":cfg["structure_model_version"],
        "route_decision_schema_version":cfg["route_decision_schema_version"],
        "development_dataset":{"dataset_id":"ROUTING_DEV_V3","sha256":_tree_hash(DATA),
            "manifest_sha256":_sha(DATA/"manifest.json"),"development_only":True,
            "prohibited_as_holdout":True},
        "benchmark":{"sha256":_sha(BENCHMARK),"documents":benchmark["documents"],
            "metrics":benchmark["metrics"],"false_standard_routes":benchmark["false_standard_routes"],
            "latency":benchmark["latency"],"ocr_calls_per_document":benchmark["ocr_calls_per_document"],
            "promotion":benchmark["promotion"]},
        "runtime":{"enable_router_v3_default":False,"evaluation_only":True,
            "rollback_flag":"ENABLE_ROUTER_V2"},
        "tuning_prohibition":"Do not tune Router V3 from observed production-representative regression images."}
    payload=json.dumps(manifest,indent=2); output.write_text(payload+"\n","utf-8")
    return manifest


if __name__=="__main__": print(json.dumps(freeze(),indent=2))
