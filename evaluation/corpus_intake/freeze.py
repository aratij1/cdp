"""Immutable corpus freeze and protected runtime/evaluation parity audit."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from packages.document_taxonomy.taxonomy import DocumentTaxonomyV1
from packages.processing_routes.contracts import PROCESSING_ROUTE_CONTRACT_VERSION
from packages.standard_form_verification.cms1500 import CMS1500Verifier
from packages.standard_form_verification.ub04 import UB04Verifier

from .contracts import CorpusIntakeBatch

CORPUS_FREEZE_VERSION = "routing-taxonomy-corpus-v1-freeze-v1.0.0"
CORPUS_BUILDER_VERSION = "routing-taxonomy-qualified-builder-v1.1.0"
PROTECTED_RUNTIME_PATHS = (
    "packages/document_routing/decision_service.py",
    "packages/document_routing/contracts.py",
    "packages/document_routing/hierarchical.py",
    "packages/standard_form_verification/cms1500.py",
    "packages/standard_form_verification/contracts.py",
    "packages/standard_form_verification/evidence.py",
    "packages/standard_form_verification/service.py",
    "packages/standard_form_verification/ub04.py",
    "packages/processing_routes/contracts.py",
    "packages/processing_routes/resolver.py",
)


def _stable_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def freeze_corpus(
    batch: CorpusIntakeBatch,
    qualification: dict,
    asset_results: dict[str, dict],
    source_results: dict[str, dict],
    review_agreement: dict,
    leakage: dict,
    baseline_path: Path,
    output: Path,
) -> dict:
    if not qualification["freeze_allowed"]:
        raise ValueError("CORPUS_QUALIFICATION_FAILED")
    baseline = json.loads(baseline_path.read_text("utf-8"))
    qualified_assets = []
    qualified_source_ids = set()
    for asset in batch.assets:
        if asset_results[asset.asset_id]["qualification_status"] != "QUALIFIED":
            continue
        row = {
            key: value for key, value in asset.model_dump(mode="json").items()
            if key not in {"asset_uri", "review_status", "qualification_status", "exclusion_reason_codes"}
        }
        row["qualification_status"] = "QUALIFIED"
        qualified_assets.append(row)
        qualified_source_ids.add(asset.source_family_id)
    qualified_assets.sort(key=lambda item: item["asset_id"])
    record = {
        "freeze_status": "FROZEN",
        "freeze_version": CORPUS_FREEZE_VERSION,
        "freeze_id": "ROUTING_TAXONOMY_CORPUS_V1_FREEZE",
        "created_at": datetime.now(UTC).isoformat(),
        "corpus_version": "ROUTING_TAXONOMY_CORPUS_V1",
        "corpus_builder_version": CORPUS_BUILDER_VERSION,
        "corpus_intake_schema_version": batch.schema_version,
        "qualification_level": qualification["qualification_level"],
        "asset_manifest_hash": _stable_hash(qualified_assets),
        "truth_hash": _stable_hash(sorted([
            (item["asset_id"], item["truth_top_level_class"], item["truth_subtype"],
             item["expected_processing_route"])
            for item in asset_results.values() if item["qualification_status"] == "QUALIFIED"
        ])),
        "source_lineage_hash": _stable_hash({
            "attestations": sorted(
                [item.model_dump(mode="json") for item in batch.source_attestations],
                key=lambda item: item["source_family_id"],
            ),
            "qualification": source_results,
        }),
        "review_adjudication_hash": _stable_hash({
            "reviews": sorted(
                [item.model_dump(mode="json") for item in batch.reviews],
                key=lambda item: (item["asset_id"], item["reviewer_id"]),
            ),
            "adjudications": sorted(
                [item.model_dump(mode="json") for item in batch.adjudications],
                key=lambda item: item["asset_id"],
            ),
            "agreement": review_agreement,
        }),
        "leakage_report_hash": _stable_hash(leakage),
        "qualification_report_hash": _stable_hash(qualification),
        "baseline_git_sha": baseline["git_sha"],
        "baseline_source_bundle_hash": baseline["source_bundle_sha256"],
        "taxonomy_version": DocumentTaxonomyV1.version,
        "verification_policy_versions": {
            "cms1500": CMS1500Verifier.policy_version,
            "ub04": UB04Verifier.policy_version,
        },
        "processing_route_contract_version": PROCESSING_ROUTE_CONTRACT_VERSION,
        "page_count": qualification["qualified"],
        "source_count": len(qualified_source_ids),
        "immutable": True,
        "loso_started": False,
    }
    if output.exists():
        existing = json.loads(output.read_text("utf-8"))
        if existing.get("freeze_status") == "FROZEN":
            immutable_keys = set(record) - {"created_at", "loso_started"}
            if all(existing.get(key) == record.get(key) for key in immutable_keys):
                return existing
            raise FileExistsError("CORPUS_FREEZE_IS_IMMUTABLE_AND_INPUTS_CHANGED")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), "utf-8")
    return record


def audit_runtime_evaluation_parity(
    root: Path,
    baseline_path: Path,
    cases: list[dict],
    qualified_ids: set[str],
    expected_truth: dict[str, dict] | None = None,
) -> dict:
    baseline = json.loads(baseline_path.read_text("utf-8"))
    file_checks = {}
    for relative in PROTECTED_RUNTIME_PATHS:
        expected = baseline["source_file_hashes"].get(relative)
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        file_checks[relative] = {"expected": expected, "actual": actual, "match": expected == actual}
    case_ids = [str(item.get("asset_id", item.get("page_id"))) for item in cases]
    expected_truth = expected_truth or {}
    truth_matches = all(
        not expected_truth
        or (
            str(case.get("truth_subtype")) == expected_truth[case_id]["truth_subtype"]
            and str(case.get("expected_processing_route"))
            == expected_truth[case_id]["expected_processing_route"]
            and str(case.get("source_family")) == expected_truth[case_id]["source_family_id"]
        )
        for case_id, case in zip(case_ids, cases)
        if case_id in expected_truth
    ) and (not expected_truth or set(case_ids) == set(expected_truth))
    case_checks = {
        "one_case_per_qualified_asset": set(case_ids) == qualified_ids and len(case_ids) == len(set(case_ids)),
        "routing_evidence_present": all(bool(item.get("routing_evidence")) for item in cases),
        "source_family_present": all(bool(item.get("source_family")) for item in cases),
        "truth_present": all(bool(item.get("truth_subtype")) and bool(item.get("expected_processing_route")) for item in cases),
        "truth_and_source_match_frozen_corpus": truth_matches,
    }
    passed = bool(cases) and all(item["match"] for item in file_checks.values()) and all(case_checks.values())
    return {
        "status": "PASS" if passed else "FAIL",
        "execution_contract": "DocumentRoutingDecisionService(runtime-parity)",
        "protected_runtime_files": file_checks,
        "case_checks": case_checks,
        "case_count": len(cases),
        "qualified_asset_count": len(qualified_ids),
        "passed": passed,
    }
