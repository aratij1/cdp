"""Freeze the observed 200-document Phase-6 rejection baseline."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from pathlib import Path

from packages.evidence import EvidencePolicy
from packages.claim_decision import ClaimDecisionService
from packages.templates import TemplateRegistry
from packages.domain.enums import ClaimFormType


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation_results/production_holdout_v2"
OUTPUT = ROOT / "evaluation_results/PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED"


def _hash(path: Path) -> str:
    digest = hashlib.sha256(); digest.update(path.read_bytes()); return digest.hexdigest()


def freeze() -> dict:
    predictions = RESULTS / "predictions.json"
    report = RESULTS / "baseline_report.json"
    if not predictions.is_file() or not report.is_file():
        raise ValueError("completed V2 baseline predictions/report are required")
    sample_manifest = next((RESULTS / "sample200_shards").glob("*/sample_manifest.json"))
    sample = json.loads(sample_manifest.read_text("utf-8"))
    registry = TemplateRegistry.load_from_directory()
    config_paths = sorted((ROOT / "config").glob("*.yaml"))
    config_digest = hashlib.sha256("".join(
        f"{path.name}:{_hash(path)}\n" for path in config_paths
    ).encode()).hexdigest()
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                          text=True).strip()
    except Exception:
        git_sha = "UNAVAILABLE"
    versions = {}
    for package in ("rapidocr-onnxruntime", "paddleocr", "paddlepaddle", "pytesseract"):
        try: versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: versions[package] = "not-installed-in-audit-env"
    payload = {
        "baseline_id": "PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED",
        "status": "FROZEN_REJECTED", "git_sha": git_sha,
        "sample_method": sample["method"], "sample_seed": sample["seed"],
        "sample_ids": sample["document_ids"],
        "sample_hash": hashlib.sha256("\n".join(sample["document_ids"]).encode()).hexdigest(),
        "predictions_sha256": _hash(predictions), "report_sha256": _hash(report),
        "dataset_archive_sha256": "56af099657cfc79b01789ed89905dcbabb2142e0219097aedc41c5d77a22f0d",
        "ground_truth_sha256": "8153c6518b3fe91f3c760f900119ed3858f6ed44b64cb350e53b2e2d915fef00",
        "configuration_sha256": config_digest,
        "templates": [
            f"{item.template_id}@{item.version}"
            for form_type in ClaimFormType
            for item in registry.all_for_form_type(form_type)
        ],
        "router_source_sha256": _hash(ROOT / "workers/page_detection/router.py"),
        "layout_engine_source_sha256": _hash(ROOT / "packages/layout_intelligence/engine.py"),
        "ocr_versions": versions,
        "evidence_policy_version": EvidencePolicy.load().version,
        "claim_policy_version": ClaimDecisionService.load().policy_version,
        "frozen_metrics": json.loads(report.read_text("utf-8")),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "baseline_manifest.json"
    path.write_text(json.dumps(payload, indent=2), "utf-8")
    return payload


if __name__ == "__main__":
    frozen = freeze(); print(json.dumps({key: frozen[key] for key in
        ("baseline_id", "status", "git_sha", "sample_hash", "predictions_sha256")}, indent=2))
