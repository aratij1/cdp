"""Immutable Git-bound candidate records, separate from historical Track A freezes."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "1a857337c200f704a159f43a8acc6c00a8d184d3"
PROFILE = "config/runtime_profiles/canonical_runtime_policy_coverage_v1.yaml"
RECORD = "docs/qualification/candidates/" + CANDIDATE + ".json"
SEMANTIC = "docs/qualification/DOCUMENT_SEMANTIC_AUTHORITY.md"


def digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def content_hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def runtime_path(name: str) -> bool:
    return (name.startswith(("packages/", "workers/")) and name.endswith(".py")) or (
        name.startswith("config/") and not name.startswith(("config/qualification/", "config/releases/"))
        and name.endswith((".yaml", ".yml", ".json"))) or name == SEMANTIC


def build(root: Path = ROOT, candidate: str = CANDIDATE) -> dict:
    commit = subprocess.check_output(["git", "rev-parse", candidate + "^{commit}"], cwd=root, text=True).strip()
    if commit != candidate:
        raise ValueError("FULL_CANDIDATE_SHA_REQUIRED")
    archive = subprocess.check_output(["git", "archive", candidate, "packages", "workers", "config", SEMANTIC], cwd=root)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        blobs = {item.name: tar.extractfile(item).read() for item in tar if item.isfile()}  # type: ignore[union-attr]
    profile = yaml.safe_load(blobs[PROFILE])
    bindings = {}
    for key in ("field_policy", "evidence_policy", "route_registry", "criticality_config", "claim_policy", "reference_config", "calibration_registry"):
        path = profile[key + "_path"]
        actual = digest(blobs[path])
        if actual != profile[key + "_sha256"]:
            raise ValueError("CANDIDATE_PROFILE_HASH_MISMATCH:" + key)
        bindings[key] = {"path": path, "sha256": actual}
    components = {name: digest(data) for name, data in sorted(blobs.items()) if runtime_path(name)}
    acceptance = {name: value for name, value in components.items() if name.startswith((
        "packages/evidence_decision/", "packages/claim_decision/", "packages/real_data_evaluation/",
        "workers/validation/", "workers/output_generation/")) or name in {
            "packages/semantic_fields.py", "packages/semantic_authority.py", "packages/field_policy.py"}}
    result = {"schema_version": "candidate-runtime-freeze-v1", "candidate_commit_sha": candidate,
              "role": "QUALIFICATION_CANDIDATE_NOT_APPROVAL", "runtime_profile": profile["profile_id"] + "@" + profile["profile_version"],
              "runtime_profile_sha256": digest(blobs[PROFILE]), "bindings": bindings,
              "semantic_authority_policy_sha256": digest(blobs[SEMANTIC]),
              "acceptance_stp_implementation_sha256": content_hash(acceptance),
              "acceptance_stp_components": acceptance, "runtime_components": components,
              "pipeline_configuration_sha256": content_hash(components),
              "hash_algorithm": "SHA256_OF_LF_NORMALIZED_GIT_BYTES; maps use canonical JSON",
              "production_qualified": False}
    result["freeze_sha256"] = content_hash(result)
    return result


def create(root: Path = ROOT) -> dict:
    record = build(root)
    path = root / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != record:
            raise ValueError("IMMUTABLE_CANDIDATE_FREEZE_EXISTS")
    else:
        with path.open("x", encoding="utf-8") as stream: stream.write(encoded)
    return record


def readiness(root: Path = ROOT) -> dict:
    path = root / RECORD
    if not path.exists(): return {"status": "MISSING", "candidate_commit_sha": CANDIDATE}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record != build(root): return {"status": "INVALID_FREEZE", "candidate_commit_sha": CANDIDATE}
        changed = [name for name, expected in record["runtime_components"].items()
                   if not (root/name).is_file() or digest((root/name).read_bytes()) != expected]
        tracked = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root, text=True).splitlines()
        changed.extend(name for name in tracked if runtime_path(name) and name not in record["runtime_components"])
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError):
        return {"status": "INVALID_FREEZE", "candidate_commit_sha": CANDIDATE}
    return {"status": "RUNTIME_DRIFT" if changed else "PASS", "candidate_commit_sha": CANDIDATE,
            "freeze_integrity": "PASS", "runtime_changed_paths": sorted(set(changed)),
            "pipeline_configuration_sha256": record["pipeline_configuration_sha256"], "production_qualified": False}
