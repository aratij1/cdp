"""Classify every frozen V2 field comparison before recovery work begins."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from evaluation.audit_production_holdout_v2 import DEFAULT_DATASET


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation_results/production_holdout_v2"
CROSSWALK = ROOT / "config/evaluation_field_crosswalk.yaml"
OUTPUT = ROOT / "evaluation_results/PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED"


def _basic(value) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper())


def _canonical(value, method: str):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if method == "NAME":
        return tuple(sorted(re.findall(r"[A-Z]+", raw.upper())))
    if method == "DATE":
        for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m%d%Y"):
            try: return datetime.strptime(raw, pattern).date().isoformat()
            except ValueError: pass
        return _basic(raw)
    if method == "CURRENCY":
        try: return Decimal(re.sub(r"[^0-9.-]", "", raw)).quantize(Decimal(".01"))
        except InvalidOperation: return _basic(raw)
    return _basic(raw)


def audit_contract() -> dict:
    crosswalk_payload = yaml.safe_load(CROSSWALK.read_text("utf-8"))
    crosswalk = crosswalk_payload["fields"]
    predictions = {item["document_id"]: item for item in
                   json.loads((RESULTS / "predictions.json").read_text("utf-8"))}
    truth = {item["document_id"]: item for item in
             (json.loads(line) for line in (DEFAULT_DATASET / "ground_truth/ground_truth.jsonl").read_text("utf-8").splitlines())
             if item["document_id"] in predictions}
    rows, categories = [], Counter()
    family_counts, field_counts = defaultdict(Counter), defaultdict(Counter)
    for document_id, expected in truth.items():
        prediction = predictions[document_id]
        for ground_field, ground_value in expected["fields"].items():
            if ground_field == "service_lines":
                continue
            spec = crosswalk.get(ground_field)
            actual = prediction["fields"].get(ground_field)
            raw = actual.get("raw") if actual else None
            final = actual.get("value") if actual else None
            applicable = not bool(spec and spec.get("routing_only"))
            exact = _basic(final) == _basic(ground_value) if actual else False
            canonical_equal = (
                _canonical(final, spec["comparison"]) == _canonical(ground_value, spec["comparison"])
                if actual and spec else False
            )
            if exact:
                category = "MATCH"
            elif spec is None:
                category = "SCHEMA_MAPPING_MISMATCH"
            elif not applicable:
                category = "FIELD_NOT_APPLICABLE"
            elif not spec.get("supported", False):
                category = "UNSUPPORTED_FIELD"
            elif actual is None and prediction["route"] in {"NON_CLAIM", "UNKNOWN_UNSTRUCTURED"}:
                category = "ROUTE_NOT_EXECUTED"
            elif actual is None and spec["canonical"] in prediction["fields"]:
                category = "FIELD_NAME_MISMATCH"
            elif actual is None:
                category = "EMPTY_PREDICTION"
            elif canonical_equal and spec["comparison"] == "NAME":
                category = "NAME_ORDER_MISMATCH"
            elif canonical_equal and spec["comparison"] == "DATE":
                category = "DATE_FORMAT_MISMATCH"
            elif canonical_equal and spec["comparison"] == "CURRENCY":
                category = "CURRENCY_FORMAT_MISMATCH"
            elif canonical_equal:
                category = "NORMALIZATION_MISMATCH"
            else:
                category = "TRUE_EXTRACTION_ERROR"
            categories[category] += 1; family_counts[expected["family"]][category] += 1
            field_counts[ground_field][category] += 1
            rows.append({
                "document_id": document_id, "truth_family": expected["family"],
                "predicted_route": prediction["route"], "ground_truth_field": ground_field,
                "canonical_CDP_field": spec["canonical"] if spec else None,
                "ground_truth_value": ground_value, "raw_prediction": raw,
                "normalized_prediction": str(_canonical(final, spec["comparison"])) if spec else _basic(final),
                "final_prediction": final,
                "comparison_method": spec["comparison"] if spec else "UNMAPPED",
                "field_applicable": applicable,
                "extractor_executed": actual is not None,
                "reason_for_empty_prediction": category if actual is None else None,
                "classification": category,
            })
    total = len(rows)
    exact_matches = categories["MATCH"]
    canonical_matches = exact_matches + sum(categories[key] for key in (
        "NAME_ORDER_MISMATCH", "DATE_FORMAT_MISMATCH", "CURRENCY_FORMAT_MISMATCH",
        "NORMALIZATION_MISMATCH",
    ))
    applicable_supported = sum(1 for row in rows if row["field_applicable"] and
                               crosswalk.get(row["ground_truth_field"], {}).get("supported"))
    true_correct = canonical_matches
    report = {
        "baseline_id": "PRODUCTION_HOLDOUT_V2_BASELINE_REJECTED",
        "crosswalk_version": crosswalk_payload["version"], "comparison_count": total,
        "exact_accuracy": exact_matches / total,
        "canonicalized_accuracy": canonical_matches / total,
        "true_extraction_accuracy_on_supported_applicable": (
            true_correct / applicable_supported if applicable_supported else None
        ),
        "category_counts": dict(categories),
        "meaningful_classification_coverage": sum(categories.values()) / total,
        "by_family": {key: dict(value) for key, value in family_counts.items()},
        "by_field": {key: dict(value) for key, value in field_counts.items()},
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "comparison_audit.json").write_text(json.dumps(rows, indent=2), "utf-8")
    (OUTPUT / "evaluation_contract_audit.json").write_text(json.dumps(report, indent=2), "utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(audit_contract(), indent=2))
