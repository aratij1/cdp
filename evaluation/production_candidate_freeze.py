"""Bind a reviewed implementation commit without granting release qualification."""

from __future__ import annotations

import hashlib
import json
import subprocess
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = r"C:\Program Files\Git\cmd\git.exe"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict:
    commit = subprocess.check_output([GIT, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output([GIT, "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != "closure/cdp-target":
        raise ValueError("UNEXPECTED_FREEZE_BRANCH")
    tracked = subprocess.check_output([GIT, "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    folders = (
        "packages/ocr/",
        "packages/claim_intelligence/",
        "packages/claim_evidence/",
        "packages/document_routing/",
        "packages/document_taxonomy/",
        "packages/field_localization/",
        "packages/real_data_evaluation/",
        "workers/standard_form_extraction/",
        "config/",
    )
    paths = [
        p
        for p in tracked
        if p
        and (
            p.startswith(folders)
            or p.startswith("evaluation/production_")
            or p == "evaluation/closure_iteration6_latency.py"
        )
        and Path(p).suffix in {".py", ".json", ".yaml", ".yml"}
    ]
    hashes = {}
    for name in paths:
        current = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        committed = subprocess.check_output([GIT, "show", commit + ":" + name], cwd=ROOT).replace(
            b"\r\n", b"\n"
        )
        if current != committed:
            raise ValueError("UNCOMMITTED_FREEZE_COMPONENT:" + name)
        hashes[name] = hashlib.sha256(current).hexdigest()
    import rapidocr_onnxruntime  # type: ignore[import-untyped]

    package = Path(rapidocr_onnxruntime.__file__).parent
    models = {p.relative_to(package).as_posix(): sha(p) for p in sorted(package.rglob("*.onnx"))}
    if not models:
        raise ValueError("OCR_MODEL_HASHES_UNAVAILABLE")
    reports = {
        name: sha(ROOT / "docs/closure" / name)
        for name in (
            "production_latency_results.json",
            "production_evidence_readiness.json",
            "production_release_readiness.json",
            "production_engineering_replay.json",
            "production_validation.json",
            "latency_contract.json",
            "runtime_capabilities.json",
            "runtime_decision.json",
            "minimum_stp_path.json",
            "form_identity_profile.json",
        )
    }
    latency = json.loads((ROOT / "docs/closure/production_latency_results.json").read_text())
    if not latency.get("selected_configuration"):
        raise ValueError("LATENCY_SELECTION_NOT_FINALIZED")
    validation = json.loads((ROOT / "docs/closure/production_validation.json").read_text())
    if not validation.get("all_required_checks_passed"):
        raise ValueError("REQUIRED_VALIDATION_NOT_PASSED")
    result = {
        "implementation_commit_sha": commit,
        "branch": branch,
        "authority": "ENGINEERING_CANDIDATE_FREEZE_NOT_RELEASE_APPROVAL",
        "component_hash_algorithm": "SHA256_OF_LF_NORMALIZED_TRACKED_BYTES",
        "component_sha256": hashes,
        "ocr_model_sha256": models,
        "runtime_versions": {
            name: version(name)
            for name in ("rapidocr-onnxruntime", "onnxruntime", "numpy", "Pillow")
        },
        "report_sha256": reports,
        "benchmark_sha256": latency["benchmark_hashes"],
        "execution_provider": "CPUExecutionProvider",
        "runtime_decision": json.loads((ROOT / "docs/closure/runtime_decision.json").read_text())["decision"],
        "truth_manifest_sha256": None,
        "production_qualified": False,
        "production_authority_enabled": False,
        "release_status": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
        "cost_configuration": "PAID_AI_ZERO_OBSERVED_TOTAL_COST_PRICING_NOT_CONFIGURED",
        "latency_configuration": latency.get(
            "selected_configuration", {"status": "PENDING_FINAL_QUALIFICATION"}
        ),
        "validation": validation,
    }
    out = ROOT / "docs/closure/CDP_PRODUCTION_CANDIDATE_FREEZE.json"
    out.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


if __name__ == "__main__":
    run()
