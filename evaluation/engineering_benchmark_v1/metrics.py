from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable


STANDARD_FAMILIES = {"CMS1500", "UB04"}
FIXED_ROUTES = {"CMS_STANDARD_EXTRACTOR", "UB_STANDARD_EXTRACTOR"}


def ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    return ordered[max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))]


def class_metrics(rows: list[dict[str, Any]], truth_key: str, prediction_key: str) -> dict[str, Any]:
    classes = sorted({str(row[truth_key]) for row in rows} | {str(row[prediction_key]) for row in rows})
    result = {}
    for label in classes:
        tp = sum(row[truth_key] == label and row[prediction_key] == label for row in rows)
        fp = sum(row[truth_key] != label and row[prediction_key] == label for row in rows)
        fn = sum(row[truth_key] == label and row[prediction_key] != label for row in rows)
        result[label] = {"support": sum(row[truth_key] == label for row in rows),
                         "true_positive": tp, "false_positive": fp, "false_negative": fn,
                         "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn)}
    return result


def confusion(rows: list[dict[str, Any]], truth_key: str, prediction_key: str) -> dict[str, dict[str, int]]:
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        matrix[str(row[truth_key])][str(row[prediction_key])] += 1
    return {truth: dict(sorted(counts.items())) for truth, counts in sorted(matrix.items())}


def _truth_top(family: str) -> str:
    if family in STANDARD_FAMILIES or family.startswith("CUSTOM_"):
        return "CLAIM"
    if family == "CLAIM_SUPPORT":
        return "CLAIM_SUPPORT"
    if family == "NON_CLAIM":
        return "NON_CLAIM"
    return "UNKNOWN"


def summarize_routing(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    for row in rows:
        row["expected_top_level"] = _truth_top(row["expected_family"])
    nonstandard = [row for row in rows if row["expected_family"] not in STANDARD_FAMILIES]
    standard = [row for row in rows if row["expected_family"] in STANDARD_FAMILIES]
    nominated = [row for row in rows if row["predicted_family"] in STANDARD_FAMILIES]
    cms = [row for row in rows if row["expected_family"] == "CMS1500"]
    ub = [row for row in rows if row["expected_family"] == "UB04"]
    safe_fallbacks = [row for row in standard if row["predicted_family"] == row["expected_family"]
                      and row["predicted_processing_route"] == "LAYOUT_STRUCTURED_EXTRACTOR"]
    false_standard = [row for row in nonstandard if row["predicted_processing_route"] in FIXED_ROUTES]
    custom = [row for row in rows if row["expected_family"].startswith("CUSTOM_")]
    support = [row for row in rows if row["expected_family"] == "CLAIM_SUPPORT"]
    nonclaim = [row for row in rows if row["expected_family"] == "NON_CLAIM"]
    unknown = [row for row in rows if row["expected_family"].startswith("UNKNOWN_")]
    wall = [row["latency_ms"]["total"] for row in rows]
    metrics = {
        "evidence_class": "ENGINEERING_BENCHMARK_ONLY",
        "production_promotion_authority": False,
        "documents": len(rows),
        "exact_family_routing_accuracy": ratio(sum(row["predicted_family"] == row["expected_family"] for row in rows), len(rows)),
        "top_level_taxonomy_accuracy": ratio(sum(row["predicted_top_level"] == row["expected_top_level"] for row in rows), len(rows)),
        "processing_route_accuracy": ratio(sum(row["predicted_processing_route"] == row["expected_processing_route"] for row in rows), len(rows)),
        "standard_nomination_precision": ratio(sum(row["expected_family"] in STANDARD_FAMILIES for row in nominated), len(nominated)),
        "standard_nomination_recall": ratio(sum(row["predicted_family"] == row["expected_family"] for row in standard), len(standard)),
        "cms_precision": class_metrics(rows, "expected_family", "predicted_family").get("CMS1500", {}).get("precision", 0.0),
        "cms_recall": ratio(sum(row["predicted_family"] == "CMS1500" for row in cms), len(cms)),
        "ub_precision": class_metrics(rows, "expected_family", "predicted_family").get("UB04", {}).get("precision", 0.0),
        "ub_recall": ratio(sum(row["predicted_family"] == "UB04" for row in ub), len(ub)),
        "custom_structured_recognition": ratio(sum(row["predicted_family"] in {"UNKNOWN_STRUCTURED", "CMS1500", "UB04"}
                                                    for row in custom), len(custom)),
        "claim_support_processing_compatibility": ratio(sum(row["predicted_processing_route"] in {
            "LAYOUT_STRUCTURED_EXTRACTOR", "UNSTRUCTURED_EXTRACTOR"} for row in support), len(support)),
        "non_claim_recall": ratio(sum(row["predicted_family"] == "NON_CLAIM" for row in nonclaim), len(nonclaim)),
        "unknown_processing_compatibility": ratio(sum(row["predicted_processing_route"] in {
            "LAYOUT_STRUCTURED_EXTRACTOR", "UNSTRUCTURED_EXTRACTOR", "SAFE_UNKNOWN"} for row in unknown), len(unknown)),
        "false_standard_authorization_count": len(false_standard),
        "false_standard_authorization_rate": ratio(len(false_standard), len(nonstandard)),
        "cms_to_ub_authorization_rate": ratio(sum(row["predicted_processing_route"] == "UB_STANDARD_EXTRACTOR" for row in cms), len(cms)),
        "ub_to_cms_authorization_rate": ratio(sum(row["predicted_processing_route"] == "CMS_STANDARD_EXTRACTOR" for row in ub), len(ub)),
        "safe_standard_fallback_count": len(safe_fallbacks),
        "safe_standard_fallback_rate": ratio(len(safe_fallbacks), len(standard)),
        "ocr_calls_per_page": ratio(sum(row.get("ocr_calls", 0) for row in rows), len(rows)),
        "cloud_api_calls": sum(row.get("cloud_api_calls", 0) for row in rows),
        "cloud_cost_usd": 0.0,
        "latency_ms": {"p50": percentile(wall, .50), "p95": percentile(wall, .95),
                       "p99": percentile(wall, .99), "mean": statistics.fmean(wall) if wall else 0.0},
        "by_family": class_metrics(rows, "expected_family", "predicted_family"),
        "by_source": {},
        "by_quality": {},
    }
    for group_key, target in (("source_dataset", metrics["by_source"]),
                              ("quality_bucket", metrics["by_quality"])):
        for group in sorted({row[group_key] for row in rows}):
            subset = [row for row in rows if row[group_key] == group]
            target[group] = {"documents": len(subset),
                "exact_family_accuracy": ratio(sum(row["predicted_family"] == row["expected_family"] for row in subset), len(subset)),
                "processing_route_accuracy": ratio(sum(row["predicted_processing_route"] == row["expected_processing_route"] for row in subset), len(subset)),
                "false_standard_authorizations": sum(row["expected_family"] not in STANDARD_FAMILIES and
                    row["predicted_processing_route"] in FIXED_ROUTES for row in subset)}
    matrices = {
        "family": confusion(rows, "expected_family", "predicted_family"),
        "top_level": confusion(rows, "expected_top_level", "predicted_top_level"),
        "processing_route": confusion(rows, "expected_processing_route", "predicted_processing_route"),
    }
    return metrics, matrices


def summarize_verification(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"evidence_class": "ENGINEERING_BENCHMARK_ONLY",
                              "production_promotion_authority": False, "documents": len(rows)}
    for family in ("CMS1500", "UB04"):
        key = f"direct_{family.lower()}_verification"
        positive = [row for row in rows if row["expected_family"] == family]
        negative = [row for row in rows if row["expected_family"] != family]
        tp = sum(row["direct_verification"][family]["status"] == "VERIFIED" for row in positive)
        fp = sum(row["direct_verification"][family]["status"] == "VERIFIED" for row in negative)
        result[key] = {"true_positive": tp, "false_positive": fp,
            "false_negative": len(positive) - tp, "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, len(positive)), "positive_support": len(positive),
            "negative_support": len(negative)}
    return result


def error_category(row: dict[str, Any]) -> str:
    truth, predicted = row["expected_family"], row["predicted_family"]
    if truth in STANDARD_FAMILIES and predicted in STANDARD_FAMILIES and truth != predicted:
        return "CMS_UB_CONFUSION"
    if truth in STANDARD_FAMILIES and truth == predicted and row["predicted_processing_route"] not in FIXED_ROUTES:
        return "STANDARD_VERIFICATION_FAILURE"
    if truth == "NON_CLAIM":
        return "NON_CLAIM_FAILURE"
    if truth == "CLAIM_SUPPORT":
        return "ATTACHMENT_OR_SUPPORT_FAILURE"
    if truth.startswith("CUSTOM_"):
        return "CUSTOM_STRUCTURE_FAILURE"
    if truth.startswith("UNKNOWN_"):
        return "UNKNOWN_FALLBACK_FAILURE"
    evidence = row.get("routing_evidence", {})
    family = truth if truth in STANDARD_FAMILIES else predicted
    if evidence.get("weighted_anchor_coverage", {}).get(family, 0) < .20:
        return "ANCHOR_MISS"
    if evidence.get("anchor_geometry_score", {}).get(family, 0) < .45:
        return "GEOMETRY_FAILURE"
    if evidence.get("standard_structure", {}).get(family, 0) < .45:
        return "STRUCTURE_FAILURE"
    if evidence.get("margin", 0) < .05:
        return "MARGIN_FAILURE"
    return "NOMINATION_POLICY_FAILURE"


def error_pareto(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    for row in rows:
        if (row["predicted_family"] != row["expected_family"] or
                row["predicted_processing_route"] != row["expected_processing_route"]):
            errors.append({"document_id": row["document_id"], "source_dataset": row["source_dataset"],
                "quality_bucket": row["quality_bucket"], "expected_family": row["expected_family"],
                "predicted_family": row["predicted_family"],
                "expected_processing_route": row["expected_processing_route"],
                "predicted_processing_route": row["predicted_processing_route"],
                "category": error_category(row), "image_path": row["image_path"],
                "tuning_allowed": row["tuning_allowed"]})
    counts = Counter(item["category"] for item in errors)
    total = len(errors)
    cumulative = 0
    pareto = []
    for category, count in counts.most_common():
        cumulative += count
        pareto.append({"category": category, "count": count, "share": ratio(count, total),
                       "cumulative_share": ratio(cumulative, total)})
    return {"error_count": total, "pareto": pareto, "errors": errors}
