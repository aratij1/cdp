"""Technology-neutral LOSO evaluator for already-produced hierarchical observations."""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path

from packages.document_routing.decision_service import DocumentRoutingDecisionService
from packages.document_routing.router import RoutingEvidence
from packages.document_taxonomy.policy import RoutingOutcome, summarize_outcomes
from packages.standard_form_verification.evidence import StandardFormEvidence


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _defined_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * quantile) - 1))]


class _TimedClassifier:
    def __init__(self, target, timings: dict[str, float]):
        self.target = target
        self.timings = timings

    def classify(self, *args, **kwargs):
        started = time.perf_counter_ns()
        result = self.target.classify(*args, **kwargs)
        self.timings["classification_nomination_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        return result


class _TimedVerificationService:
    def __init__(self, target, timings: dict[str, float]):
        self.target = target
        self.timings = timings

    def verify(self, *args, **kwargs):
        started = time.perf_counter_ns()
        result = self.target.verify(*args, **kwargs)
        self.timings["verification_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        return result


class _TimedRouteResolver:
    def __init__(self, target, timings: dict[str, float]):
        self.target = target
        self.timings = timings

    def resolve(self, *args, **kwargs):
        started = time.perf_counter_ns()
        result = self.target.resolve(*args, **kwargs)
        self.timings["route_resolution_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        return result


def _source_metrics(rows: list[dict]) -> dict:
    outcomes = tuple(RoutingOutcome.model_validate({
        **row["outcome"],
        "verification_status": row["outcome"].get("verification_status", row.get("verification_status")),
        "verified_family": row["outcome"].get("verified_family", row.get("verified_family")),
    }) for row in rows)
    result = summarize_outcomes(outcomes)
    result["total_pages"] = len(rows)
    truth_top = [row.get("truth_top_level") for row in rows]
    pred_top = [row.get("predicted_top_level") for row in rows]
    classes = ("CLAIM", "CLAIM_SUPPORT", "NON_CLAIM", "UNKNOWN")
    recalls = {name: _defined_ratio(sum(t == name and p == name for t, p in zip(truth_top, pred_top)),
                            sum(t == name for t in truth_top)) for name in classes}
    precisions = {name: _defined_ratio(sum(t == name and p == name for t, p in zip(truth_top, pred_top)),
                               sum(p == name for p in pred_top)) for name in classes}
    f1 = {name: (_ratio(2 * precisions[name] * recalls[name], precisions[name] + recalls[name])
                 if precisions[name] is not None and recalls[name] is not None else None)
          for name in classes}
    supported_f1 = [value for value in f1.values() if value is not None]
    supported_recall = [value for value in recalls.values() if value is not None]
    truth_standard = [bool(row.get("truth_standard")) for row in rows]
    pred_standard = [bool(row.get("standard_nominated")) for row in rows]
    result.update({
        "top_level_taxonomy_recall": recalls,
        "top_level_taxonomy_precision": precisions,
        "top_level_taxonomy_f1": f1,
        "top_level_macro_f1": sum(supported_f1) / len(supported_f1) if supported_f1 else None,
        "top_level_worst_recall": min(supported_recall) if supported_recall else None,
        "standard_precision": _defined_ratio(sum(t and p for t, p in zip(truth_standard, pred_standard)), sum(pred_standard)),
        "standard_recall": _defined_ratio(sum(t and p for t, p in zip(truth_standard, pred_standard)), sum(truth_standard)),
        "non_standard_precision": _defined_ratio(sum(not t and not p for t, p in zip(truth_standard, pred_standard)),
                                          sum(not p for p in pred_standard)),
        "non_standard_recall": _defined_ratio(sum(not t and not p for t, p in zip(truth_standard, pred_standard)),
                                       sum(not t for t in truth_standard)),
        "false_standard_nomination_rate": _defined_ratio(sum(not t and p for t, p in zip(truth_standard, pred_standard)),
                                                  sum(not t for t in truth_standard)),
    })
    for family in ("CMS1500", "UB04"):
        truth = [row.get("truth_subtype") == family for row in rows]
        nominated = [row.get("nominated_family") == family for row in rows]
        verified = [row.get("verified_family") == family for row in rows]
        result[f"{family.lower()}_nomination_precision"] = _defined_ratio(sum(t and p for t, p in zip(truth, nominated)), sum(nominated))
        result[f"{family.lower()}_nomination_recall"] = _defined_ratio(sum(t and p for t, p in zip(truth, nominated)), sum(truth))
        result[f"{family.lower()}_verification_recall"] = _defined_ratio(sum(t and p for t, p in zip(truth, verified)), sum(truth))
        result[f"{family.lower()}_verification_precision"] = _defined_ratio(sum(t and p for t, p in zip(truth, verified)), sum(verified))
        truth_rows = [row for row in rows if row.get("truth_subtype") == family]
        result[f"{family.lower()}_not_verified_rate"] = _ratio(
            sum(row.get("verification_status") == "NOT_VERIFIED" for row in truth_rows), len(truth_rows))
        result[f"{family.lower()}_ambiguous_rate"] = _ratio(
            sum(row.get("verification_status") == "AMBIGUOUS" for row in truth_rows), len(truth_rows))
        result[f"{family.lower()}_verified_count"] = sum(
            row.get("verification_status") == "VERIFIED" for row in truth_rows
        )
        result[f"{family.lower()}_not_verified_count"] = sum(
            row.get("verification_status") == "NOT_VERIFIED" for row in truth_rows
        )
        result[f"{family.lower()}_ambiguous_count"] = sum(
            row.get("verification_status") == "AMBIGUOUS" for row in truth_rows
        )
    latency = sorted(float(row.get("latency_ms", 0)) for row in rows)
    result["latency_p50_ms"] = statistics.median(latency) if latency else 0.0
    result["latency_p95_ms"] = _percentile(latency, .95)
    result["latency_p99_ms"] = _percentile(latency, .99)
    stage_names = ("classification_nomination_ms", "verification_ms", "route_resolution_ms")
    result["stage_latency_ms"] = {}
    for stage in stage_names:
        values = [float(row.get("stage_latency_ms", {}).get(stage, 0.0)) for row in rows]
        result["stage_latency_ms"][stage] = {
            "p50": statistics.median(values) if values else 0.0,
            "p95": _percentile(values, .95),
            "p99": _percentile(values, .99),
        }
    result["stage_latency_contract"] = {
        "classification_and_nomination": "ATOMIC_IN_DETERMINISTIC_HIERARCHICAL_BASELINE",
        "verification": "StandardFormVerificationService.verify",
        "route_resolution": "ProcessingRouteResolver.resolve",
    }
    result["unverified_fixed_authorization_count"] = sum(x.unverified_fixed_authorization for x in outcomes)
    result["route_extractor_firewall_violations"] = result["unverified_fixed_authorization_count"]
    result["cost_weighted_routing_score"] = max(0.0, 1.0 - result["mean_routing_risk_score"] / 100.0)
    result["top_level_processing_impact"] = {
        name: _defined_ratio(sum(t == name and not outcome.processing_route_correct
                                 for t, outcome in zip(truth_top, outcomes)),
                             sum(t == name for t in truth_top)) for name in classes}
    for family in ("CMS1500", "UB04"):
        truth_rows = [row for row in rows if row.get("truth_subtype") == family]
        other_route = "UB_STANDARD_EXTRACTOR" if family == "CMS1500" else "CMS_STANDARD_EXTRACTOR"
        expected_route = (
            "CMS_STANDARD_EXTRACTOR" if family == "CMS1500" else "UB_STANDARD_EXTRACTOR"
        )
        result[f"{family.lower()}_funnel"] = {
            "truth_pages": len(truth_rows),
            "classified_claim": sum(row.get("predicted_top_level") == "CLAIM" for row in truth_rows),
            "classified_standard": sum(bool(row.get("standard_nominated")) for row in truth_rows),
            "family_nominated": sum(row.get("nominated_family") == family for row in truth_rows),
            "family_verified": sum(row.get("verified_family") == family for row in truth_rows),
            "fixed_authorized": sum(row["outcome"]["authorized_route"] == expected_route for row in truth_rows),
            "safe_fallback": sum(RoutingOutcome.model_validate({**row["outcome"],
                "verification_status": row.get("verification_status"),
                "verified_family": row.get("verified_family")}).safe_standard_fallback for row in truth_rows),
            "wrong_standard_authorization": sum(row["outcome"]["authorized_route"] == other_route for row in truth_rows),
            "safe_unknown": sum(row["outcome"]["authorized_route"] == "SAFE_UNKNOWN" for row in truth_rows),
        }
    return result


def run_runtime_parity_loso(cases: list[dict], service: DocumentRoutingDecisionService | None = None) -> dict:
    """Run held-out cases through the exact runtime service; deterministic baseline has no fit step."""
    base_service = service or DocumentRoutingDecisionService()
    rows = []
    sources = sorted({case["source_family"] for case in cases})
    for held_out in sources:
        for case in (item for item in cases if item["source_family"] == held_out):
            routing = RoutingEvidence.model_validate(case["routing_evidence"])
            standard = (StandardFormEvidence.model_validate(case["standard_evidence"])
                        if case.get("standard_evidence") else None)
            stage_timings: dict[str, float] = {}
            service = DocumentRoutingDecisionService(
                classifier=_TimedClassifier(base_service.classifier, stage_timings),
                verification_service=_TimedVerificationService(
                    base_service.verification_service, stage_timings
                ),
                route_resolver=_TimedRouteResolver(base_service.route_resolver, stage_timings),
            )
            started = time.perf_counter()
            decision = service.decide(case["document_id"], case["page_id"], routing, standard,
                                      evaluation_only=True)
            latency_ms = (time.perf_counter() - started) * 1000
            verification = decision.standard_verification
            rows.append({"source_family": held_out,
                "train_source_families": [source for source in sources if source != held_out],
                "truth_top_level": case["truth_top_level"],
                "predicted_top_level": decision.classification.top_level_class.value,
                "truth_standard": case["truth_subtype"] in {"CMS1500", "UB04"},
                "standard_nominated": decision.classification.standard_candidate,
                "truth_subtype": case["truth_subtype"],
                "nominated_family": (decision.classification.document_subtype.value
                                     if decision.classification.standard_candidate else None),
                "verified_family": (verification.candidate_family.value
                                    if verification and verification.status.value == "VERIFIED" else None),
                "verification_status": verification.status.value if verification else None,
                "latency_ms": latency_ms,
                "stage_latency_ms": stage_timings,
                "outcome": {"truth": case["truth_subtype"],
                    "prediction": decision.classification.document_subtype.value,
                    "authorized_route": decision.processing_route.value,
                    "expected_route": case["expected_processing_route"],
                    "verification_status": verification.status.value if verification else None,
                    "verified_family": (verification.candidate_family.value
                                        if verification and verification.status.value == "VERIFIED" else None),
                    "abstained": decision.processing_route.value == "SAFE_UNKNOWN"}})
    report = evaluate(rows)
    report["execution_contract"] = "DocumentRoutingDecisionService(runtime-parity)"
    report["rotations"] = {source: {"held_out": source,
        "develop_sources": [other for other in sources if other != source]} for source in sources}
    return report


def evaluate(records: list[dict]) -> dict:
    by_source: dict[str, list[dict]] = defaultdict(list)
    for row in records:
        by_source[row["source_family"]].append(row)
    source_metrics = {source: _source_metrics(rows) for source, rows in sorted(by_source.items())}
    metric_names = sorted({name for result in source_metrics.values() for name, value in result.items()
                           if isinstance(value, (int, float)) or value is None})
    aggregate = {}
    lower_is_better = ("false_", "misroute", "risk_score", "abstention", "latency_",
                       "safe_standard_fallback", "unverified_fixed")
    for metric in metric_names:
        values = sorted(result.get(metric) for result in source_metrics.values()
                        if isinstance(result.get(metric), (int, float)))
        if not values:
            aggregate[metric] = {"worst_source": None, "median_source": None, "best_source": None}
            continue
        low_metric = any(token in metric for token in lower_is_better)
        aggregate[metric] = {"worst_source": max(values) if low_metric else min(values),
                             "median_source": values[len(values)//2],
                             "best_source": min(values) if low_metric else max(values)}
    family_groups = {
        "CMS": {"CMS1500"}, "UB": {"UB04"},
        "CUSTOM": {"CUSTOM_PROFESSIONAL", "CUSTOM_INSTITUTIONAL", "OTHER_STRUCTURED_CLAIM"},
        "SUPPORT": {"EOB", "ITEMIZED_BILL", "MEDICAL_INVOICE", "LAB_REPORT", "CLINICAL_NOTE",
                    "CORRESPONDENCE", "OTHER_ATTACHMENT"},
        "NON_CLAIM": {"COVER_PAGE", "DOCUMENT_SEPARATOR", "ADMINISTRATIVE",
                      "BLANK_OR_NEAR_BLANK", "OTHER_NON_CLAIM"},
        "UNKNOWN": {"UNKNOWN"},
    }
    family_source = {}
    for source, rows in by_source.items():
        family_source[source] = {}
        for family, labels in family_groups.items():
            subset = [row for row in rows if row.get("truth_subtype") in labels]
            if not subset: continue
            outcomes = tuple(RoutingOutcome.model_validate({**row["outcome"],
                "verification_status": row.get("verification_status"),
                "verified_family": row.get("verified_family")}) for row in subset)
            family_source[source][family] = {"pages": len(subset),
                "taxonomy_accuracy": sum(x.truth == x.prediction for x in outcomes) / len(outcomes),
                "processing_route_accuracy": sum(x.processing_route_correct for x in outcomes) / len(outcomes),
                "false_standard_authorizations": sum(x.false_standard_authorization for x in outcomes),
                "safe_standard_fallbacks": sum(x.safe_standard_fallback for x in outcomes),
                "mean_routing_risk_score": sum(x.risk_score for x in outcomes) / len(outcomes)}
    return {"split_policy": "LEAVE_ONE_SOURCE_FAMILY_OUT", "source_metrics": source_metrics,
            "aggregate": aggregate, "family_source_matrix": family_source}


def main(input_path: str, output_path: str) -> None:
    records = json.loads(Path(input_path).read_text("utf-8"))
    Path(output_path).write_text(json.dumps(evaluate(records), indent=2), "utf-8")
