"""Create an auditable registry without changing runtime lifecycle or model state."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main(root: Path) -> dict:
    artifacts = {
        "ROUTER_V3": root / "config/router_v3_freeze.json",
        "ROUTER_V4": root / "evaluation/experiments/router_v4_prevalidation_run_1.json",
        "LIGHTGBM_V1": root / "evaluation/experiments/router_ml_eligibility_v1.json",
        "XGBOOST_V1": root / "evaluation/experiments/router_ml_eligibility_v1.json",
        "VISUAL_ROUTER_V1": root / "evaluation_results/router_visual_v1/baseline_freeze.json",
        "VISUAL_CONTRADICTION_V1": root / "evaluation_results/visual_safety_dev_v1/contradiction_report.json",
    }
    registry = {
        "freeze_id": "ROUTING_REJECTED_EXPERIMENTS_7A9",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                  capture_output=True).stdout.strip(),
        "lifecycle_config_hash": digest(root / "config/router_lifecycle.json"),
        "taxonomy_config_hash": digest(root / "config/document_taxonomy_v1.json"),
        "components": {name: {"status": "REJECTED_OR_NOT_ELIGIBLE", "artifact": str(path.relative_to(root)),
                              "artifact_sha256": digest(path), "runtime_authority": False}
                       for name, path in artifacts.items()},
        "candidate": "NOT_CREATED", "external_holdout": "BLOCKED", "shadow": "BLOCKED",
        "phase_7b_extraction": "PAUSED", "production_router_v4_changed": False,
    }
    output = root / "evaluation_results/routing_taxonomy_v1/rejected_experiments_freeze.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, indent=2), "utf-8")
    return registry


if __name__ == "__main__":
    print(json.dumps(main(Path(__file__).resolve().parents[2]), indent=2))
