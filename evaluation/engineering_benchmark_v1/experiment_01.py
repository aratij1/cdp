"""EXP-7A13-01: evaluation-only grid evidence semantic mapping.

The router already emits a raw page grid score.  Baseline verification maps a
family composite into the CMS service-grid and UB institutional-grid evidence
slots.  This experiment changes only that mapping, never thresholds, router
scores, nomination, production configuration, or the route firewall.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from packages.document_routing.decision_service import DocumentRoutingDecisionService
from packages.document_routing.router import MultiSignalRoute, RoutingEvidence
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.standard_form_verification.evidence import evidence_from_router_features
from packages.standard_form_verification.service import StandardFormVerificationService

from .build_manifest import RESULT_ROOT, ROOT
from .metrics import FIXED_ROUTES, STANDARD_FAMILIES, ratio, summarize_routing
from .routing_benchmark import PHASE_ROOT


def _mapped(family: DocumentClass, routing: RoutingEvidence):
    baseline = evidence_from_router_features(family, None, routing)
    if family == DocumentClass.CMS1500:
        return baseline.model_copy(update={"service_grid_score": max(
            baseline.service_grid_score, routing.grid_score)})
    regions = dict(baseline.region_layout_scores)
    regions["institutional_grid"] = max(regions.get("institutional_grid", 0), routing.grid_score)
    return baseline.model_copy(update={"region_layout_scores": regions})


def _verification(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for family in STANDARD_FAMILIES:
        positive = [row for row in rows if row["expected_family"] == family]
        negative = [row for row in rows if row["expected_family"] != family]
        tp = sum(row["experiment_direct_verification"][family]["status"] == "VERIFIED" for row in positive)
        fp = sum(row["experiment_direct_verification"][family]["status"] == "VERIFIED" for row in negative)
        result[family] = {"true_positive": tp, "false_positive": fp,
            "false_negative": len(positive) - tp, "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, len(positive)), "positive_support": len(positive),
            "negative_support": len(negative)}
    return result


def _evaluate(source_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    service = StandardFormVerificationService()
    decision_service = DocumentRoutingDecisionService(verification_service=service)
    results = []
    timings = []
    for source in source_rows:
        row = dict(source)
        routing = RoutingEvidence.model_validate(source["routing_evidence"])
        started = time.perf_counter()
        direct = {}
        for family in (DocumentClass.CMS1500, DocumentClass.UB04):
            result = service.verify(_mapped(family, routing))
            direct[family.value] = result.model_dump(mode="json")
        nominated = (DocumentClass(routing.route.value)
                     if routing.route in {MultiSignalRoute.CMS1500, MultiSignalRoute.UB04} else None)
        evidence = _mapped(nominated, routing) if nominated else None
        decision = decision_service.decide(source["document_id"], source["page_id"], routing,
                                           evidence, evaluation_only=True)
        timings.append((time.perf_counter() - started) * 1000)
        row["experiment_direct_verification"] = direct
        row["predicted_processing_route"] = decision.processing_route.value
        row["standard_verification"] = (decision.standard_verification.model_dump(mode="json")
                                        if decision.standard_verification else None)
        results.append(row)
    return results, (sorted(timings)[max(0, int(.95 * len(timings)) - 1)] if timings else 0.0)


def run() -> dict[str, Any]:
    source_rows = [json.loads(line) for line in
                   (RESULT_ROOT / "routing_details.jsonl").read_text("utf-8").splitlines()]
    # Metrics must match the deterministic finalized baseline scope.
    baseline_metrics = json.loads((PHASE_ROOT / "routing_metrics.json").read_text("utf-8"))
    scoped_ids = set()
    # routing_metrics has 766 records; use manifest order to preserve the same scope.
    manifest = json.loads((RESULT_ROOT / "manifest.json").read_text("utf-8"))
    scoped_ids.update(row["document_id"] for row in manifest["records"][:baseline_metrics["documents"]])
    source_rows = [row for row in source_rows if row["document_id"] in scoped_ids]
    experiment_rows, p95_added = _evaluate(source_rows)
    tuning = [row for row in experiment_rows if row["tuning_allowed"]]
    observation = [row for row in experiment_rows if not row["tuning_allowed"]]
    tuning_metrics, _ = summarize_routing(tuning)
    observation_metrics, _ = summarize_routing(observation)
    all_metrics, _ = summarize_routing(experiment_rows)
    verification = {"tuning_permitted": _verification(tuning),
                    "observation_only": _verification(observation),
                    "all_executed": _verification(experiment_rows)}
    baseline_tuning = [row for row in source_rows if row["tuning_allowed"]]
    baseline_tuning_metrics, _ = summarize_routing(baseline_tuning)
    false_standard = tuning_metrics["false_standard_authorization_rate"]
    route_gain = tuning_metrics["processing_route_accuracy"] - baseline_tuning_metrics["processing_route_accuracy"]
    gates = {
        "tuning_processing_route_gain_positive": route_gain > 0,
        "false_standard_authorization_lte_half_pct": false_standard <= .005,
        "no_cms_ub_cross_authorization": (tuning_metrics["cms_to_ub_authorization_rate"] == 0 and
                                          tuning_metrics["ub_to_cms_authorization_rate"] == 0),
        "cms_direct_verification_precision_gte_99pct": verification["tuning_permitted"]["CMS1500"]["precision"] >= .99,
        "ub_direct_verification_precision_gte_99pct": verification["tuning_permitted"]["UB04"]["precision"] >= .99,
        "added_decision_p95_lte_20ms": p95_added <= 20,
    }
    decision = "PROMOTE_TO_NEXT_ENGINEERING_CANDIDATE" if all(gates.values()) else "REJECT"
    report = {
        "experiment_id": "EXP-7A13-01-GRID-EVIDENCE-MAPPING",
        "evidence_class": "ENGINEERING_BENCHMARK_ONLY", "evaluation_only": True,
        "production_changed": False, "change": {
            "CMS1500": "service_grid_score=max(family_composite, raw_grid_score)",
            "UB04": "institutional_grid=max(family_composite, raw_grid_score)",
            "threshold_changes": 0, "new_models": 0,
        },
        "selection_scope": "tuning_allowed records only",
        "tuning_documents": len(tuning), "observation_documents": len(observation),
        "baseline_tuning_processing_route_accuracy": baseline_tuning_metrics["processing_route_accuracy"],
        "experiment_tuning_processing_route_accuracy": tuning_metrics["processing_route_accuracy"],
        "processing_route_accuracy_gain": route_gain,
        "tuning_metrics": tuning_metrics, "observation_metrics": observation_metrics,
        "all_metrics": all_metrics, "verification_metrics": verification,
        "added_decision_p95_ms": p95_added, "gates": gates, "decision": decision,
    }
    PHASE_ROOT.mkdir(parents=True, exist_ok=True)
    (PHASE_ROOT / "experiment_01.json").write_text(json.dumps(report, indent=2), "utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
