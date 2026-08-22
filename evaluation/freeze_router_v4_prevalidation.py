"""Freeze Router V4 before development-data population without claiming promotion."""
from __future__ import annotations
import hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"evaluation_results/router_v4/prevalidation/manifest.json"
FILES=[ROOT/"config/document_routing_v4.yaml",ROOT/"packages/document_routing/v4.py",
       ROOT/"packages/document_routing/structural.py",ROOT/"workers/page_detection/routing_input.py"]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def freeze():
    git=lambda *a: subprocess.run(["git",*a],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()
    status=git("status","--porcelain","--untracked-files=no")
    value={"freeze_id":"ROUTER_V4_PREVALIDATION_BASELINE","created_at":datetime.now(timezone.utc).isoformat(),
      "git_sha":git("rev-parse","HEAD"),"tracked_worktree_clean":not bool(status),"router_version":"4.0-dev",
      "configuration_hash":sha(FILES[0]),"preprocessing_version":"routing-input-v4.0",
      "preprocessing_hash":sha(FILES[3]),"anchor_version":"weighted-anchors-v3.0-corroborative",
      "zone_version":"normalized-zones-v3.0","structural_descriptor_version":"normalized-structure-v4.0",
      "decision_contract_version":"4.0","ocr":{"engine":"tesseract-cli","version":subprocess.run(
          [r"C:\Program Files\Tesseract-OCR\tesseract.exe","--version"],text=True,capture_output=True).stdout.splitlines()[0]},
      "feature_flags":{"enable_router_v3":False,"enable_router_v4":False},
      "source_hashes":{str(p.relative_to(ROOT)):sha(p) for p in FILES},"status":"PREVALIDATION_FROZEN"}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(value,indent=2),"utf-8"); return value
if __name__=="__main__": print(json.dumps(freeze(),indent=2))
