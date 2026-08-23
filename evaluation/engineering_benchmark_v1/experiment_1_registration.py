"""Phase 7A.13B Experiment 1: registration evidence for standard verification.

Selection is driven by the frozen tuning-only Pareto.  The experiment does not
change router nomination, verifier thresholds, resolver policy, templates, or
production configuration.  It supplies the existing verifier's already-defined
TEMPLATE_REGISTRATION evidence from the repository's PHI-free reference assets.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

from packages.document_routing.decision_service import DocumentRoutingDecisionService
from packages.document_routing.router import MultiSignalRoute, RoutingEvidence
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.domain.enums import ClaimFormType
from packages.standard_form_verification.evidence import evidence_from_router_features
from packages.templates.registry import TemplateRegistry
from workers.standard_form_extraction.consumer import _align_or_rescale

from .build_manifest import RESULT_ROOT, ROOT
from .freeze import load_frozen_manifest
from .metrics import FIXED_ROUTES, percentile, ratio
from .phase7a13b import run as finalize
from .routing_benchmark import PHASE_ROOT


REFERENCE = {"CMS1500": ROOT / "config/templates/reference_images/cms1500_v02_12.png",
             "UB04": ROOT / "config/templates/reference_images/ub04_v2014.png"}


def _baseline_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    standards = [row for row in rows if row["expected_family"] in {"CMS1500", "UB04"}]
    nonstandard = [row for row in rows if row["expected_family"] not in {"CMS1500", "UB04"}]
    return {"documents": len(rows),
        "processing_route_accuracy": ratio(sum(row["predicted_processing_route"] == row["expected_processing_route"]
                                                for row in rows), len(rows)),
        "standard_fixed_route_recall": ratio(sum(row["predicted_processing_route"] == row["expected_processing_route"]
                                                 for row in standards), len(standards)),
        "cms_fixed_route_recall": ratio(sum(row["expected_family"] == "CMS1500" and
            row["predicted_processing_route"] == "CMS_STANDARD_EXTRACTOR" for row in rows),
            sum(row["expected_family"] == "CMS1500" for row in rows)),
        "ub_fixed_route_recall": ratio(sum(row["expected_family"] == "UB04" and
            row["predicted_processing_route"] == "UB_STANDARD_EXTRACTOR" for row in rows),
            sum(row["expected_family"] == "UB04" for row in rows)),
        "false_standard_authorization_rate": ratio(sum(row["predicted_processing_route"] in FIXED_ROUTES
                                                        for row in nonstandard), len(nonstandard)),
        "safe_fallback_count": sum(row["expected_family"] in {"CMS1500", "UB04"} and
            row["predicted_family"] == row["expected_family"] and
            row["predicted_processing_route"] == "LAYOUT_STRUCTURED_EXTRACTOR" for row in rows)}


def _registration_score(record, family: str, templates) -> tuple[float, float, str]:
    started = time.perf_counter()
    template = templates[family]
    with Image.open(ROOT / record.image_path) as opened:
        image = opened.convert("L")
        image.load()
    resized = image.resize((template.reference_dimensions.width_px,
                            template.reference_dimensions.height_px))
    with Image.open(REFERENCE[family]) as opened:
        reference = opened.convert("L")
        reference.load()
    _, method, evidence = _align_or_rescale(resized, template, reference)
    score = float(evidence.alignment_confidence) if evidence else 0.0
    return score, (time.perf_counter() - started) * 1000, method


def _candidate(rows: list[dict[str, Any]], manifest_by_id, templates) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    service = DocumentRoutingDecisionService()
    output, latency, methods = [], [], {}
    for source in rows:
        row = dict(source)
        routing = RoutingEvidence.model_validate(source["routing_evidence"])
        family = routing.route.value if routing.route in {MultiSignalRoute.CMS1500, MultiSignalRoute.UB04} else None
        standard_evidence = None
        if family:
            score, elapsed, method = _registration_score(manifest_by_id[row["document_id"]], family, templates)
            latency.append(elapsed)
            methods[method] = methods.get(method, 0) + 1
            standard_evidence = evidence_from_router_features(DocumentClass(family), None, routing,
                template_registration_score=score, template_version=templates[family].version)
            row["experiment_registration_score"] = score
            row["experiment_registration_method"] = method
        decision = service.decide(row["document_id"], row["page_id"], routing, standard_evidence,
                                  evaluation_only=True)
        row["predicted_processing_route"] = decision.processing_route.value
        row["standard_verification"] = (decision.standard_verification.model_dump(mode="json")
                                        if decision.standard_verification else None)
        output.append(row)
    return output, {"registration_calls": len(latency), "registration_method_counts": methods,
                    "added_latency_ms": {"p50": percentile(latency, .50), "p95": percentile(latency, .95),
                                         "p99": percentile(latency, .99)}}


def run() -> dict[str, Any]:
    manifest = load_frozen_manifest()
    manifest_by_id = {row.document_id: row for row in manifest.records}
    routing_by_id = {json.loads(line)["document_id"]: json.loads(line) for line in
                     (RESULT_ROOT / "routing_details.jsonl").read_text("utf-8").splitlines()}
    missing = [row.document_id for row in manifest.records if row.document_id not in routing_by_id]
    if missing:
        raise RuntimeError(f"cannot start experiment before complete baseline: {len(missing)} pages missing")
    pareto = json.loads((PHASE_ROOT / "error_pareto.json").read_text("utf-8"))
    tuning_pareto = sorted((item for item in pareto["categories"] if item["tuning_permitted_count"]),
                           key=lambda item: -item["tuning_permitted_count"])
    historical_exclusions = {"GEOMETRY_FAILURE": "REM-01 content-bound geometry was previously rejected",
                             "CUSTOM_STRUCTURE_FAILURE": "not a standard verification failure"}
    selected = next(item for item in tuning_pareto if item["category"] not in historical_exclusions)
    if selected["category"] not in {"SAFE_FALLBACK", "STANDARD_VERIFICATION_FAILURE"}:
        raise RuntimeError(f"highest remaining correctable category is not verifier-related: {selected['category']}")
    tuning = [routing_by_id[row.document_id] for row in manifest.records if row.tuning_allowed]
    baseline = _baseline_summary(tuning)
    registry = TemplateRegistry.load_from_directory()
    templates = {"CMS1500": registry.latest_for_form_type(ClaimFormType.CMS1500),
                 "UB04": registry.latest_for_form_type(ClaimFormType.UB04)}
    candidate_rows, cost = _candidate(tuning, manifest_by_id, templates)
    candidate = _baseline_summary(candidate_rows)
    gain = candidate["processing_route_accuracy"] - baseline["processing_route_accuracy"]
    target_gain = candidate["standard_fixed_route_recall"] - baseline["standard_fixed_route_recall"]
    tuning_gate = {
        "processing_route_gain_gte_2pp": gain >= .02,
        "standard_fixed_route_recall_gain_gte_2pp": target_gain >= .02,
        "false_standard_authorization_no_material_regression": (
            candidate["false_standard_authorization_rate"] <= baseline["false_standard_authorization_rate"] + .001),
        "cms_does_not_regress": candidate["cms_fixed_route_recall"] >= baseline["cms_fixed_route_recall"],
        "ub_does_not_regress": candidate["ub_fixed_route_recall"] >= baseline["ub_fixed_route_recall"],
        "added_p95_lte_20pct_of_baseline_route_p95": cost["added_latency_ms"]["p95"] <=
            json.loads((PHASE_ROOT / "routing_metrics.json").read_text("utf-8"))["splits"]["tuning_permitted"]["latency_ms"]["p95"] * .20,
    }
    observation_result: dict[str, Any] = {"status": "NOT_RUN_TUNING_GATE_FAILED"}
    decision = "REJECT"
    if all(tuning_gate.values()):
        observation = [routing_by_id[row.document_id] for row in manifest.records if not row.tuning_allowed]
        observation_baseline = _baseline_summary(observation)
        observation_rows, observation_cost = _candidate(observation, manifest_by_id, templates)
        observation_candidate = _baseline_summary(observation_rows)
        neutral = (observation_candidate["processing_route_accuracy"] >= observation_baseline["processing_route_accuracy"] and
                   observation_candidate["false_standard_authorization_rate"] <=
                   observation_baseline["false_standard_authorization_rate"] + .001)
        observation_result = {"status": "RUN_ONCE", "baseline": observation_baseline,
                              "candidate": observation_candidate, "cost": observation_cost,
                              "improved_or_neutral": neutral}
        decision = "PROMOTE_ENGINEERING_CANDIDATE" if neutral else "REJECT"
    report = {"experiment_id": "EXP-7A13B-01-TEMPLATE-REGISTRATION-EVIDENCE",
        "hypothesis": "Existing template-registration evidence can safely resolve the largest remaining tuning-only standard-verification fallback category without threshold changes.",
        "selected_from_tuning_pareto": selected,
        "excluded_historical_or_out_of_scope_categories": historical_exclusions,
        "tuning_data_used": 430, "observation_data_used_for_selection": 0,
        "files_changed": ["evaluation/engineering_benchmark_v1/experiment_1_registration.py"],
        "production_files_changed": [], "baseline": baseline, "candidate": candidate,
        "absolute_processing_route_gain": gain, "absolute_target_recall_gain": target_gain,
        "cost": cost, "tuning_gate": tuning_gate, "observation_only_result": observation_result,
        "decision": decision, "stop_after_experiment_1": True}
    _write_path = PHASE_ROOT / "experiment_1.json"
    _write_path.write_text(json.dumps(report, indent=2), "utf-8")
    finalize(experiment=report)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
