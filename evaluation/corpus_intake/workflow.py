"""Fail-closed Phase 7A.12 intake -> qualification -> freeze -> LOSO workflow."""
from __future__ import annotations

import json
from pathlib import Path

from evaluation.routing.development_gate import evaluate_gate
from evaluation.routing.leave_one_source_out import run_runtime_parity_loso

from .contracts import CorpusIntakeBatch
from .freeze import audit_runtime_evaluation_parity, freeze_corpus
from .integrity import inspect_assets
from .qualification import (
    APPROVED_PHI,
    APPROVED_USAGE,
    assess_source_attestations,
    audit_leakage,
    coverage_report,
    qualification_gate,
    qualify_assets,
    record_residual_leakage,
)
from .review import create_blind_assignments, resolve_reviews

PHASE7A12_OUTPUT_FILES = (
    "intake_summary.json",
    "qualification_summary.json",
    "source_attestations.json",
    "review_agreement.json",
    "leakage_report.json",
    "corpus_freeze.json",
    "loso_results.json",
    "routing_funnel.json",
    "family_source_matrix.json",
    "development_gate.json",
    "decision.json",
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str), "utf-8")


def _gate_status(values: list[bool], has_input: bool) -> str:
    return "NOT_EVALUATED" if not has_input else "PASS" if all(values) else "FAIL"


def _routing_funnel(loso: dict) -> dict:
    if not loso.get("source_metrics"):
        return {"status": "NOT_RUN", "sources": {}}
    sources = {}
    for source, metrics in loso["source_metrics"].items():
        sources[source] = {
            "total": metrics.get("total_pages"),
            "top_level": {
                "precision": metrics.get("top_level_taxonomy_precision"),
                "recall": metrics.get("top_level_taxonomy_recall"),
            },
            "standard": {
                "precision": metrics.get("standard_precision"),
                "recall": metrics.get("standard_recall"),
                "false_nomination_rate": metrics.get("false_standard_nomination_rate"),
            },
            "cms": metrics.get("cms1500_funnel"),
            "ub": metrics.get("ub04_funnel"),
            "verification": {
                "cms_precision": metrics.get("cms1500_verification_precision"),
                "cms_recall": metrics.get("cms1500_verification_recall"),
                "ub_precision": metrics.get("ub04_verification_precision"),
                "ub_recall": metrics.get("ub04_verification_recall"),
            },
            "processing_route_accuracy": metrics.get("processing_route_accuracy"),
            "false_standard_authorization_rate": metrics.get("false_standard_authorization_rate"),
            "safe_standard_fallback_rate": metrics.get("safe_standard_fallback_rate"),
        }
    return {"status": "COMPLETE", "sources": sources}


def _classify_bottleneck(loso: dict, gate: dict) -> str | None:
    if not loso.get("source_metrics"):
        return None
    values = {name: item["value"] for name, item in gate["checks"].items()}
    if values.get("top_level_worst_recall") is None or values["top_level_worst_recall"] < .95:
        return "TAXONOMY"
    if values.get("standard_precision") is None or values["standard_precision"] < .99 \
            or values.get("standard_recall") is None or values["standard_recall"] < .95:
        return "STANDARD_NON_STANDARD"
    if values.get("cms1500_nomination_recall") is None \
            or values["cms1500_nomination_recall"] < .98 \
            or values.get("ub04_nomination_recall") is None \
            or values["ub04_nomination_recall"] < .98:
        return "CMS_UB_NOMINATION"
    verification = [
        metrics.get(name)
        for metrics in loso["source_metrics"].values()
        for name in ("cms1500_verification_recall", "ub04_verification_recall")
        if metrics.get(name) is not None
    ]
    if verification and min(verification) < .98:
        return "STANDARD_VERIFICATION"
    if values.get("processing_route_accuracy") is None or values["processing_route_accuracy"] < .98:
        return "PROCESSING_ROUTE"
    return "NONE"


def run_phase7a12(
    batch: CorpusIntakeBatch,
    *,
    root: Path,
    output_dir: Path,
    asset_root: Path | None = None,
    reviewer_ids: tuple[str, ...] = (),
    loso_cases: list[dict] | None = None,
    baseline_path: Path | None = None,
) -> dict:
    """Run only stages supported by supplied governed evidence; stop rather than infer."""
    root = root.resolve()
    baseline_path = baseline_path or root / "config/hierarchical_routing_baseline_v1.json"
    if batch.assets and asset_root is None:
        integrity = {
            item.asset_id: {"asset_id": item.asset_id, "integrity_passed": False,
                            "reason_codes": ["ASSET_ROOT_NOT_SUPPLIED"]}
            for item in batch.assets
        }
    elif batch.assets:
        integrity = inspect_assets(batch.assets, asset_root)
    else:
        integrity = {}
    source_results = assess_source_attestations(batch.assets, batch.source_attestations)
    leakage = audit_leakage(batch.assets)
    blocked_assets = set(leakage["blocked_asset_ids"])
    review_eligible_assets = tuple(
        asset for asset in batch.assets
        if integrity.get(asset.asset_id, {}).get("integrity_passed")
        and asset.split_eligibility
        and asset.asset_id not in blocked_assets
        and asset.phi_status in APPROVED_PHI
        and asset.usage_status in APPROVED_USAGE
        and source_results.get(asset.source_family_id, {}).get("status") == "PASS"
    )
    review_eligible_ids = {asset.asset_id for asset in review_eligible_assets}
    review_results, review_agreement = resolve_reviews(
        review_eligible_assets,
        tuple(item for item in batch.reviews if item.asset_id in review_eligible_ids),
        tuple(item for item in batch.adjudications if item.asset_id in review_eligible_ids),
    )
    review_agreement["asset_resolutions"] = review_results
    assignments = (
        create_blind_assignments(review_eligible_assets, reviewer_ids)
        if reviewer_ids and review_eligible_assets else []
    )
    asset_results = qualify_assets(
        batch.assets, integrity, source_results, review_results, leakage
    )
    record_residual_leakage(leakage, asset_results)
    coverage = coverage_report(batch.assets, asset_results)
    qualification = qualification_gate(
        batch.assets, asset_results, source_results, review_agreement, leakage, coverage
    )
    intake_summary = {
        "stage": "QUALIFIED_CORPUS_INTAKE",
        "input_assets": len(batch.assets),
        "integrity": integrity,
        "review_assignments": assignments,
        "asset_results": asset_results,
        "corpus_version": "ROUTING_TAXONOMY_CORPUS_V1",
    }

    freeze_record: dict = {
        "freeze_status": "NOT_CREATED",
        "reason": "CORPUS_QUALIFICATION_REQUIRED",
    }
    parity = {"status": "NOT_RUN", "reason": "CORPUS_NOT_FROZEN"}
    loso: dict = {"status": "BLOCKED", "reason": "CORPUS_QUALIFICATION_REQUIRED",
                  "source_metrics": {}, "aggregate": {}, "family_source_matrix": {}}
    development = evaluate_gate(loso)
    if qualification["freeze_allowed"]:
        freeze_record = freeze_corpus(
            batch, qualification, asset_results, source_results, review_agreement,
            leakage, baseline_path, output_dir / "corpus_freeze.json"
        )
        qualified_ids = {
            asset_id for asset_id, item in asset_results.items()
            if item["qualification_status"] == "QUALIFIED"
        }
        expected_truth = {
            asset.asset_id: {
                "truth_subtype": asset.truth_subtype.value,
                "expected_processing_route": asset.expected_processing_route.value,
                "source_family_id": asset.source_family_id,
            }
            for asset in batch.assets if asset.asset_id in qualified_ids
        }
        if loso_cases is None:
            parity = {"status": "NOT_RUN", "reason": "RUNTIME_EVALUATION_CASES_NOT_SUPPLIED"}
            loso = {"status": "BLOCKED", "reason": "RUNTIME_EVALUATION_CASES_NOT_SUPPLIED",
                    "source_metrics": {}, "aggregate": {}, "family_source_matrix": {}}
        else:
            parity = audit_runtime_evaluation_parity(
                root, baseline_path, loso_cases, qualified_ids, expected_truth
            )
            if parity["passed"]:
                loso = run_runtime_parity_loso(loso_cases)
                loso["status"] = "COMPLETE"
                loso["runtime_evaluation_parity"] = parity
            else:
                loso = {"status": "BLOCKED", "reason": "RUNTIME_EVALUATION_PARITY_FAILED",
                        "runtime_evaluation_parity": parity, "source_metrics": {},
                        "aggregate": {}, "family_source_matrix": {}}
        development = evaluate_gate(loso)

    funnel = _routing_funnel(loso)
    bottleneck = _classify_bottleneck(loso, development)
    worst_source = None
    if loso.get("source_metrics"):
        worst_source = min(
            loso["source_metrics"],
            key=lambda source: loso["source_metrics"][source].get("processing_route_accuracy", 0),
        )
    aggregate = loso.get("aggregate", {})
    metric = lambda name: aggregate.get(name, {}).get("worst_source")
    has_assets = bool(batch.assets)
    phi_gate = _gate_status(
        [asset.phi_status in APPROVED_PHI for asset in batch.assets]
        + [item.phi_status in APPROVED_PHI for item in batch.source_attestations], has_assets
    )
    usage_gate = _gate_status(
        [asset.usage_status in APPROVED_USAGE for asset in batch.assets]
        + [item.usage_status in APPROVED_USAGE for item in batch.source_attestations], has_assets
    )
    decision = {
        "STAGE": "PHASE_7A_12_QUALIFIED_CORPUS_INTAKE_AND_LOSO",
        "INPUT ASSETS": len(batch.assets),
        "QUALIFIED": qualification["qualified"],
        "EXCLUDED": qualification["excluded"],
        "PENDING": qualification["pending"],
        "INDEPENDENT SOURCES": coverage["independent_sources"],
        "PHI GATE": phi_gate,
        "USAGE GATE": usage_gate,
        "LINEAGE GATE": _gate_status(
            [item["status"] == "PASS" for item in source_results.values()], has_assets
        ),
        "DUPLICATE GATE": "NOT_EVALUATED" if not has_assets else (
            "PASS" if leakage["residual_exact_duplicate_leakage_count"] == 0
            and leakage["residual_cross_split_lineage_leakage_count"] == 0 else "FAIL"
        ),
        "REVIEW COVERAGE": qualification["review_coverage"],
        "REVIEW AGREEMENT": review_agreement["dimensions"],
        "CORPUS STATUS": qualification["corpus_status"],
        "LOSO STATUS": loso["status"],
        "WORST SOURCE": worst_source,
        "FALSE STANDARD AUTHORIZATION": metric("false_standard_authorization_rate"),
        "SAFE FALLBACK": metric("safe_standard_fallback_rate"),
        "PROCESSING ROUTE ACCURACY": metric("processing_route_accuracy"),
        "TEST RESULTS": "NOT_RUN_BY_INTAKE_WORKFLOW",
        "DECISION": "PASS" if development["passed"] else "NEEDS_MORE_DATA",
        "BOTTLENECK": bottleneck,
        "NEXT ACTION": (
            "Freeze HIERARCHICAL_ROUTER_CANDIDATE_1, then run frozen A/B/C/D once."
            if development["passed"] else
            "Supply the missing authorized assets, attestations, blind reviews, and adjudications."
            if not qualification["freeze_allowed"] else
            "Supply parity-complete runtime evidence cases and run first deterministic LOSO."
            if loso["status"] == "BLOCKED" else
            f"Create separate development reproductions for the {bottleneck} bottleneck; do not tune on LOSO."
        ),
        "FROZEN A/B/C/D RUN": False,
        "EXTERNAL HOLDOUT": "BLOCKED",
        "PHASE 7B": "PAUSED",
        "PRODUCTION ROUTER V4": "UNCHANGED",
    }

    artifacts = {
        "intake_summary.json": intake_summary,
        "qualification_summary.json": {**qualification, "coverage": coverage},
        "source_attestations.json": {
            "attestations": [item.model_dump(mode="json") for item in batch.source_attestations],
            "qualification": source_results,
        },
        "review_agreement.json": review_agreement,
        "leakage_report.json": leakage,
        "corpus_freeze.json": freeze_record,
        "loso_results.json": loso,
        "routing_funnel.json": funnel,
        "family_source_matrix.json": (
            loso.get("family_source_matrix") or coverage["family_source_matrix"]
        ),
        "development_gate.json": development,
        "decision.json": decision,
    }
    for filename, value in artifacts.items():
        if filename == "corpus_freeze.json" and freeze_record.get("freeze_status") == "FROZEN":
            continue
        _write_json(output_dir / filename, value)
    return {"decision": decision, "qualification": qualification,
            "runtime_evaluation_parity": parity, "artifacts": artifacts}
