"""Fail-closed candidate freeze: impossible unless every cross-source gate passed."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; REPORT=ROOT/"evaluation_results/router_v4/cross_source/report.json"
def freeze(report_path:Path=REPORT):
    report=json.loads(report_path.read_text("utf-8"))
    if not report["gates"]["ALL"]: raise RuntimeError("Router V4 candidate freeze refused: cross-source gates failed")
    manifests=sorted((ROOT/"evaluation_results/router_v4/datasets").glob("*/manifest.json"))
    value={"freeze_id":"ROUTER_V4_CANDIDATE_1","git_sha":subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip(),
      "config_hash":hashlib.sha256((ROOT/"config/document_routing_v4.yaml").read_bytes()).hexdigest(),"dataset_hashes":{p.parent.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in manifests},
      "evaluation_report_hash":hashlib.sha256(report_path.read_bytes()).hexdigest(),"status":"CROSS_SOURCE_VALIDATED","runtime":"EVALUATION_ONLY"}
    out=ROOT/"evaluation_results/router_v4/candidate_1/manifest.json"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(value,indent=2),"utf-8"); return value
if __name__=="__main__": print(json.dumps(freeze(),indent=2))
