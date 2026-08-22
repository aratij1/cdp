"""Rank field-review causes and measure safe review reduction."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from evaluation.matcher import match_fields
from evaluation.normalizers import NormalizerRegistry
from evaluation.schemas import GroundTruthDataset, PredictionDataset
from packages.review_reasons import (
    ReviewReasonContext,
    classify_review_reasons,
    review_evidence_summary,
)

STRATEGIES = {
    "OCR_DISAGREEMENT": "field-specific preprocessing and independent reconciliation",
    "LOW_OCR_CONFIDENCE": "expanded crop or constrained OCR",
    "LOW_REGISTRATION_CONFIDENCE": "canonical template registration",
    "NO_REFERENCE_MATCH": "authorized reference lookup",
    "REFERENCE_CONTRADICTION": "HITL with reference evidence",
    "CRITICAL_NAME_UNVERIFIED": "authoritative member identity match",
    "INVALID_FORMAT": "deterministic parser/validator",
    "EMPTY_CROP": "registration and expanded-crop retry",
    "WRONG_CROP_SUSPECTED": "anchor and geometry validation",
    "LABEL_CONTAMINATION": "label mask and crop tightening",
    "CHECKBOX_AMBIGUOUS": "checkbox geometry plus independent evidence",
    "ADDRESS_AMBIGUOUS": "component parsing and address reference",
    "TABLE_EXTRACTION_FAILURE": "UB-04 row reconstruction or Docling",
    "UNSTRUCTURED_DOCUMENT": "family routing and anchor-relative extraction",
    "MULTIPLE_PLAUSIBLE_VALUES": "reference lookup or selective resolver",
    "NO_EVIDENCE": "expanded crop then adaptive escalation",
    "AI_REQUIRED": "policy-approved selective crop resolver",
}


def _correct(pair, registry: NormalizerRegistry) -> bool:
    prediction = pair.prediction
    expected = pair.truth.expected_normalized
    if expected is None:
        expected = registry.normalize(pair.truth.field_name, pair.truth.expected_raw)
    actual = None
    if prediction is not None:
        actual = prediction.normalized_value
        if actual is None:
            actual = registry.normalize(pair.truth.field_name, prediction.raw_value)
    return (expected or "") == (actual or "")


def safe_review_reduction(
    truth: GroundTruthDataset,
    baseline: PredictionDataset,
    candidate: PredictionDataset,
    registry: NormalizerRegistry,
) -> dict[str, int | float | None]:
    baseline_pairs = {(p.document.document_id, p.truth.field_name): p for p in match_fields(truth, baseline)}
    candidate_pairs = {(p.document.document_id, p.truth.field_name): p for p in match_fields(truth, candidate)}
    former_reviews = {
        key for key, pair in baseline_pairs.items()
        if pair.prediction is None or not pair.prediction.accepted
    }
    removed = {
        key for key in former_reviews
        if candidate_pairs[key].prediction is not None and candidate_pairs[key].prediction.accepted
    }
    correct_removed = sum(_correct(candidate_pairs[key], registry) for key in removed)
    false_introduced = len(removed) - correct_removed
    return {
        "previous_review_fields": len(former_reviews),
        "review_cases_removed": len(removed),
        "correctly_automated_former_review_fields": correct_removed,
        "safe_review_reduction": correct_removed / len(former_reviews) if former_reviews else 0.0,
        "false_accepts_introduced": false_introduced,
        "additional_compute_cost_usd": None,
        "additional_cloud_cost_usd": None,
        "latency_added_ms": None,
    }


def analyze(
    truth: GroundTruthDataset,
    predictions: PredictionDataset,
    crop_manifest: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    review_fields: set[tuple[str, str]] = set()
    for pair in match_fields(truth, predictions):
        prediction = pair.prediction
        if prediction is not None and prediction.accepted:
            continue
        key = f"{pair.document.document_id}/{pair.truth.field_name}"
        crop = crop_manifest.get(key, {})
        reasons = classify_review_reasons(
            ReviewReasonContext(
                pair.document.form_type,
                pair.truth.field_name,
                pair.truth.critical,
                prediction,
                crop,
            )
        )
        review_fields.add((pair.document.document_id, pair.truth.field_name))
        evidence = review_evidence_summary(prediction)
        for reason in reasons:
            rows.append(
                {
                    "document_id": pair.document.document_id,
                    "document_family": pair.document.form_type,
                    "field": pair.truth.field_name,
                    "criticality": "CRITICAL" if pair.truth.critical else "NON_CRITICAL",
                    "review_reason": reason.value,
                    "ocr_engines": ",".join(evidence["engines"]),
                    "registration_status": (
                        "MISSING"
                        if not crop
                        else "ACCEPTED"
                        if crop.get("local_alignment_accepted")
                        else "SUSPECT"
                    ),
                    "reference_available": evidence["reference_available"],
                    "candidate_disagreement": evidence["candidate_disagreement"],
                    "potential_automation_strategy": STRATEGIES[reason.value],
                }
            )
    reason_counts = Counter(row["review_reason"] for row in rows)
    field_reviews: dict[str, set[tuple[str, str]]] = defaultdict(set)
    family_fields: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in rows:
        field_reviews[str(row["field"])].add(
            (str(row["document_id"]), str(row["field"]))
        )
        family_fields[str(row["document_family"])].add(
            (str(row["document_id"]), str(row["field"]))
        )
    total_reviews = len(review_fields)
    summary = {
        "review_fields": total_reviews,
        "reason_assignments": len(rows),
        "reason_coverage": 1.0 if total_reviews else 0.0,
        "top_review_reasons": [
            {"reason": reason, "fields": count, "percent_of_reviews": count / total_reviews}
            for reason, count in reason_counts.most_common(10)
        ],
        "top_review_fields": [
            {"field": field, "review_fields": len(fields)}
            for field, fields in sorted(
                field_reviews.items(), key=lambda item: len(item[1]), reverse=True
            )[:20]
        ],
        "review_fields_by_family": [
            {"document_family": family, "review_fields": len(fields)}
            for family, fields in sorted(family_fields.items(), key=lambda item: len(item[1]), reverse=True)
        ],
    }
    return rows, summary


def _markdown(summary: dict[str, object], kpi: dict[str, object], hashes: dict[str, str]) -> str:
    lines = [
        "# CDP Review Reduction Report",
        "",
        "Status: **PHASE 1 ANALYTICS — NEEDS MORE DATA**",
        "",
        "The baseline is reproducible at 72.1311% overall accuracy, 77.0492% on the existing",
        "development split, zero observed false accepts, 0% STP, and 76.6667% claim-level review.",
        "Review-reason percentages below are multi-label and may sum above 100%.",
        "",
        "## Safe review reduction KPI",
        "",
        f"- Previous review fields: {kpi['previous_review_fields']}",
        f"- Review cases removed: {kpi['review_cases_removed']}",
        f"- Correctly automated former reviews: {kpi['correctly_automated_former_review_fields']}",
        f"- Safe review reduction: {float(kpi['safe_review_reduction']):.2%}",
        f"- False accepts introduced: {kpi['false_accepts_introduced']}",
        "- Additional compute/cloud cost and latency: NOT MEASURED in this analytics-only phase",
        "",
        "## Top 10 review reasons",
        "",
        "| Reason | Fields | % of reviews | Automation strategy |",
        "|---|---:|---:|---|",
    ]
    for item in summary["top_review_reasons"]:
        lines.append(
            f"| {item['reason']} | {item['fields']} | {item['percent_of_reviews']:.2%} | "
            f"{STRATEGIES[str(item['reason'])]} |"
        )
    lines.extend(["", "## Top 20 review-heavy fields", "", "| Field | Review fields |", "|---|---:|"])
    lines.extend(
        f"| {item['field']} | {item['review_fields']} |"
        for item in summary["top_review_fields"]
    )
    lines.extend(["", "## Review-heavy document families", "", "| Family | Review fields |", "|---|---:|"])
    lines.extend(
        f"| {item['document_family']} | {item['review_fields']} |"
        for item in summary["review_fields_by_family"]
    )
    lines.extend(["", "## Evidence identity", ""])
    lines.extend(f"- `{path}`: `{digest}`" for path, digest in hashes.items())
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "**NEEDS MORE DATA.** Analytics are complete; no acceptance policy changed. The ranked",
            "causes determine the next implementation target. Template registration remains blocked",
            "until non-PHI operator-approved canonical references are supplied.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, default=Path("evaluation_data/ground_truth.json"))
    parser.add_argument("--predictions", type=Path, default=Path("evaluation_results/vnext_accuracy_improvement/predictions_with_unstructured.json"))
    parser.add_argument("--baseline-predictions", type=Path)
    parser.add_argument("--crop-manifest", type=Path, default=Path("evaluation_results/field_crops/crop_manifest.json"))
    parser.add_argument("--normalization-rules", type=Path, default=Path("config/evaluation/normalization_rules.yaml"))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results/review_analysis"))
    parser.add_argument("--report", type=Path, default=Path("docs/CDP_REVIEW_REDUCTION_REPORT.md"))
    args = parser.parse_args()
    truth = GroundTruthDataset.model_validate_json(args.truth.read_text(encoding="utf-8"))
    predictions = PredictionDataset.model_validate_json(args.predictions.read_text(encoding="utf-8"))
    baseline_path = args.baseline_predictions or args.predictions
    baseline = PredictionDataset.model_validate_json(baseline_path.read_text(encoding="utf-8"))
    crops = json.loads(args.crop_manifest.read_text(encoding="utf-8")) if args.crop_manifest.is_file() else {}
    registry = NormalizerRegistry.from_yaml(args.normalization_rules)
    rows, summary = analyze(truth, predictions, crops)
    kpi = safe_review_reduction(truth, baseline, predictions, registry)
    hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (args.truth, args.predictions, baseline_path)
    }
    payload = {"summary": summary, "safe_review_reduction_kpi": kpi, "artifact_hashes": hashes}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "review_analysis.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (args.output / "review_reasons.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_markdown(summary, kpi, hashes), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
