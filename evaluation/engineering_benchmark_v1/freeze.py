from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from packages.document_routing.decision_service import DocumentRoutingDecisionService
from packages.document_taxonomy.taxonomy import DocumentTaxonomyV1
from packages.processing_routes.contracts import PROCESSING_ROUTE_CONTRACT_VERSION
from packages.processing_routes.resolver import ProcessingRouteResolver
from packages.standard_form_verification.cms1500 import CMS1500Verifier
from packages.standard_form_verification.ub04 import UB04Verifier
from workers.page_detection.routing_input import ROUTING_INPUT_PIPELINE_VERSION

from .build_manifest import RESULT_ROOT, ROOT
from .contracts import EngineeringBenchmarkManifest
from .routing_benchmark import PHASE_ROOT


RUNTIME_FILES = (
    "config/document_routing.yaml",
    "packages/document_routing/router.py",
    "packages/document_routing/decision_service.py",
    "packages/document_routing/hierarchical.py",
    "packages/standard_form_verification/evidence.py",
    "packages/standard_form_verification/cms1500.py",
    "packages/standard_form_verification/ub04.py",
    "packages/processing_routes/resolver.py",
    "config/templates/cms1500_v02_12.yaml",
    "config/templates/ub04_v2014.yaml",
)


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def load_frozen_manifest() -> EngineeringBenchmarkManifest:
    path = PHASE_ROOT / "benchmark_manifest.json"
    manifest = EngineeringBenchmarkManifest.model_validate_json(path.read_text("utf-8"))
    calculated = _sha_bytes(json.dumps(
        [row.model_dump(mode="json") for row in manifest.records],
        sort_keys=True, separators=(",", ":")).encode())
    if calculated != manifest.manifest_sha256:
        raise ValueError("ENGINEERING_BENCHMARK_V1 manifest content changed after freeze")
    return manifest


def freeze() -> dict:
    source = RESULT_ROOT / "manifest.json"
    inventory_path = RESULT_ROOT / "inventory.json"
    if not source.is_file() or not inventory_path.is_file():
        raise FileNotFoundError("build ENGINEERING_BENCHMARK_V1 before freezing")
    manifest = EngineeringBenchmarkManifest.model_validate_json(source.read_text("utf-8"))
    if manifest.record_count != 1230:
        raise ValueError(f"expected exactly 1230 unique pages, got {manifest.record_count}")
    tuning = sum(row.tuning_allowed for row in manifest.records)
    if tuning != 430:
        raise ValueError(f"expected 430 tuning-permitted pages, got {tuning}")
    inventory = json.loads(inventory_path.read_text("utf-8"))
    if len(inventory["duplicates_removed"]) != 210:
        raise ValueError("expected exactly 210 duplicate exclusions")
    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    frozen_manifest = PHASE_ROOT / "benchmark_manifest.json"
    existing_freeze = PHASE_ROOT / "benchmark_freeze.json"
    if existing_freeze.is_file():
        existing = json.loads(existing_freeze.read_text("utf-8"))
        if existing["manifest_sha256"] != manifest.manifest_sha256:
            raise ValueError("attempted to replace frozen ENGINEERING_BENCHMARK_V1")
        return existing
    shutil.copyfile(source, frozen_manifest)
    (PHASE_ROOT / "duplicate_exclusions.json").write_text(json.dumps({
        "benchmark_id": manifest.dataset_id,
        "candidate_pages": inventory["candidate_count"],
        "unique_pages": inventory["unique_count"],
        "duplicate_count": len(inventory["duplicates_removed"]),
        "exclusions": inventory["duplicates_removed"],
    }, indent=2), "utf-8")
    page_hashes = [{"document_id": row.document_id, "page_id": row.page_id,
                    "sha256": row.sha256} for row in manifest.records]
    truth_payload = [{"document_id": row.document_id, "page_id": row.page_id,
                      "expected_family": row.expected_family,
                      "expected_processing_route": row.expected_processing_route,
                      "truth_fields": row.truth_fields} for row in manifest.records]
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                          text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        git_sha = "UNAVAILABLE"
    runtime_hashes = {relative: _sha(ROOT / relative) for relative in RUNTIME_FILES}
    config_hashes = {relative: value for relative, value in runtime_hashes.items()
                     if relative.startswith("config/")}
    freeze_payload = {
        "benchmark_id": manifest.dataset_id,
        "evidence_class": "ENGINEERING_BENCHMARK_ONLY",
        "production_promotion_authority": False,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "manifest_sha256": manifest.manifest_sha256,
        "frozen_manifest_file_sha256": _sha(frozen_manifest),
        "page_hash_list_sha256": _sha_bytes(json.dumps(page_hashes, sort_keys=True,
                                                        separators=(",", ":")).encode()),
        "truth_sha256": _sha_bytes(json.dumps(truth_payload, sort_keys=True,
                                               separators=(",", ":")).encode()),
        "candidate_pages": inventory["candidate_count"],
        "unique_pages": manifest.record_count,
        "duplicates_removed": len(inventory["duplicates_removed"]),
        "tuning_permitted": tuning,
        "observation_only": manifest.record_count - tuning,
        "family_distribution": dict(sorted(Counter(row.expected_family for row in manifest.records).items())),
        "source_dataset_identity": dict(sorted(Counter(row.source_dataset for row in manifest.records).items())),
        "page_sha256": page_hashes,
        "tuning_boundary": [{"document_id": row.document_id,
                             "status": "TUNING_PERMITTED" if row.tuning_allowed else "OBSERVATION_ONLY"}
                            for row in manifest.records],
        "runtime_file_hashes": runtime_hashes,
        "configuration_hashes": config_hashes,
        "versions": {
            "document_routing_decision_service": DocumentRoutingDecisionService.version,
            "taxonomy": DocumentTaxonomyV1.version,
            "cms_verifier": CMS1500Verifier.policy_version,
            "ub_verifier": UB04Verifier.policy_version,
            "processing_route_contract": PROCESSING_ROUTE_CONTRACT_VERSION,
            "processing_route_policy": ProcessingRouteResolver.policy_version,
            "routing_preprocessing": ROUTING_INPUT_PIPELINE_VERSION,
            "routing_ocr": "Tesseract 5.x PSM 11",
            "field_ocr": "RapidOCR-ONNX rapidocr-onnxruntime",
            "cms_template": "cms1500@02-12",
            "ub_template": "ub04@2014",
        },
        "unknown_unstructured": {"sample_size": 5, "status": "LOW_SAMPLE_SUPPORT",
                                 "hard_release_gate": False},
    }
    existing_freeze.write_text(json.dumps(freeze_payload, indent=2), "utf-8")
    return freeze_payload


if __name__ == "__main__":
    result = freeze()
    print(json.dumps({key: result[key] for key in (
        "benchmark_id", "manifest_sha256", "unique_pages", "duplicates_removed",
        "tuning_permitted", "observation_only")}, indent=2))
