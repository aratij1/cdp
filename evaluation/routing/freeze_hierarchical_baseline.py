"""Freeze the Phase 7A.10 architectural baseline without running frozen datasets."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from evaluation.routing.build_taxonomy_corpus import CORPUS_BUILDER_VERSION
from packages.document_taxonomy.taxonomy import DocumentTaxonomyV1
from packages.processing_routes.contracts import PROCESSING_ROUTE_CONTRACT_VERSION
from packages.standard_form_verification.cms1500 import CMS1500Verifier
from packages.standard_form_verification.ub04 import UB04Verifier


BASELINE_VERSION = "hierarchical-routing-baseline-v1.0.0"
SOURCE_PATHS = (
    "packages/document_taxonomy",
    "packages/document_routing/decision_service.py",
    "packages/document_routing/contracts.py",
    "packages/document_routing/hierarchical.py",
    "packages/standard_form_verification",
    "packages/processing_routes",
    "packages/extraction_routing.py",
    "workers/page_detection/consumer.py",
    "workers/standard_form_extraction/consumer.py",
    "evaluation/routing/build_taxonomy_corpus.py",
    "evaluation/routing/leave_one_source_out.py",
    "config/document_taxonomy_v1.json",
    "config/routing_taxonomy_corpus_v1.yaml",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(root: Path) -> dict:
    files: list[Path] = []
    for relative in SOURCE_PATHS:
        path = root / relative
        files.extend(sorted(path.rglob("*.py"))) if path.is_dir() else files.append(path)
    hashes = {path.relative_to(root).as_posix(): _sha(path) for path in files}
    bundle_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                             text=True, check=True).stdout.strip()
    diff = subprocess.run(["git", "diff", "--binary", "HEAD", "--", *SOURCE_PATHS], cwd=root,
                          capture_output=True, check=True).stdout
    freeze_record = {
        "baseline_version": BASELINE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "source_tree_state": "DIRTY_RELATIVE_TO_GIT_SHA" if diff else "CLEAN",
        "source_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "source_bundle_sha256": bundle_hash,
        "source_file_hashes": hashes,
        "taxonomy_version": DocumentTaxonomyV1.version,
        "verification_policy_versions": {
            "service": "standard-form-verification-v1",
            "cms1500": CMS1500Verifier.policy_version,
            "ub04": UB04Verifier.policy_version,
        },
        "processing_route_contract_version": PROCESSING_ROUTE_CONTRACT_VERSION,
        "processing_route_policy_version": "processing-route-policy-v1",
        "corpus_builder_version": CORPUS_BUILDER_VERSION,
        "corpus": "ROUTING_TAXONOMY_CORPUS_V1_ACQUISITION_REQUIRED",
        "frozen_abcd_run": False,
        "candidate_created": False,
        "production_router_v4_changed": False,
    }
    output = root / "config/hierarchical_routing_baseline_v1.json"
    output.write_text(json.dumps(freeze_record, indent=2), "utf-8")
    return freeze_record


if __name__ == "__main__":
    record = freeze(Path(__file__).resolve().parents[2])
    print(json.dumps({key: record[key] for key in (
        "baseline_version", "git_sha", "source_tree_state", "source_bundle_sha256",
        "taxonomy_version", "verification_policy_versions", "processing_route_contract_version",
        "corpus_builder_version", "frozen_abcd_run")}, indent=2))
