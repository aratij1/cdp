from __future__ import annotations

import hashlib, json
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RESULT=ROOT/"evaluation_results/PHASE7B_ROUTE_CONDITIONED_EXTRACTION_V1"
OUTPUT=ROOT/"config/phase7b_route_conditioned_freeze.json"


def _sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    report=json.loads((RESULT/"report.json").read_text("utf-8"))
    manifest={"freeze_id":"PHASE7B_ROUTE_CONDITIONED_EXTRACTION_V1",
        "frozen_at":datetime.now(UTC).isoformat(),"evidence_class":report["evidence_class"],
        "untouched":False,"tuning_permitted":False,"status":"DIAGNOSTIC_FROZEN_PHASE7B_PAUSED",
        "artifacts":{name:_sha(RESULT/name) for name in
            ("report.json","document_routes.json","field_diagnostics.json")},
        "measurable":{"CMS1500":"MEASURED_ON_ROUTE_CORRECT_SUBSET",
            "UNKNOWN_UNSTRUCTURED":"MEASURED_ON_ROUTE_CORRECT_SUBSET",
            "UB04":"NOT_MEASURABLE_DUE_TO_ROUTING",
            "UNKNOWN_STRUCTURED":"NOT_MEASURABLE_DUE_TO_ROUTING"}}
    OUTPUT.write_text(json.dumps(manifest,indent=2)+"\n","utf-8"); return manifest


if __name__=="__main__": print(json.dumps(freeze(),indent=2))
