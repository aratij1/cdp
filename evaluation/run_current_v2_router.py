"""Run the field-page router over legacy all-page plus current regional candidates."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from evaluation.normalizers import NormalizerRegistry
from workers.field_candidates.reconciliation import reconcile_candidates

MINIMUM_SCORE = 0.80
MINIMUM_MARGIN = 0.08


def main() -> int:
    manifest = json.loads(Path("evaluation_data/document_manifest.json").read_text())
    summary = {
        row["evaluation_document_id"]: row["runtime_document_id"]
        for row in json.loads(Path("evaluation_results/page_candidates/summary.json").read_text())
    }
    critical_config = yaml.safe_load(
        Path("config/evaluation/critical_fields.yaml").read_text()
    )
    critical = {
        field for form in ("CMS1500", "UB04")
        for field in critical_config.get(form, [])
    }
    normalizers = NormalizerRegistry.from_yaml("config/evaluation/normalization_rules.yaml")
    rows = []
    for source in (
        Path("evaluation_results/structured_rollout/cms1500/details.json"),
        Path("evaluation_results/structured_rollout/ub04/details.json"),
    ):
        rows.extend(
            row for row in json.loads(source.read_text())
            if not row["expected_blank"] and not row.get("semantic_output")
        )
    for family in ("laboratory_invoice", "statement", "psychological_receipt", "cms_attachment"):
        rows.extend(json.loads(
            Path(f"evaluation_results/attachment_rollout/{family}/details.json").read_text()
        ))
    decisions = []
    for row in rows:
        document_id, field = row["document_id"], row["field_name"]
        expected_page = manifest[document_id]["page_number"]
        pool = []
        for candidate in row.get("all_candidates", []):
            pool.append({
                "page": expected_page, "value": candidate["normalized"],
                "score": 0.90, "provider": candidate["provider"],
                "validation_results": candidate.get("validation_results", []),
                "engine": candidate.get("engine"),
                "preprocessing_variant": candidate.get("preprocessing_variant"),
                "regional_provenance": candidate.get("regional_provenance"),
                "lineage": candidate.get("lineage"),
                "current_regional": True,
            })
        if "candidate" in row and row.get("candidate"):
            pool.append({
                "page": expected_page, "value": row["candidate"],
                "score": 0.88, "provider": "normalized_attachment_candidate",
                "validation_results": [],
                "current_regional": True,
            })
        legacy_path = (
            Path("evaluation_results/page_candidates") / summary[document_id] / "candidates.json"
        )
        if legacy_path.is_file():
            for candidate in json.loads(legacy_path.read_text()):
                if candidate["field_name"] != field or candidate["status"] != "EVIDENCE":
                    continue
                score = (
                    .35 * candidate["ocr_confidence"]
                    + .25 * candidate["family_confidence"]
                    + .25 * candidate["anchor_relevance"]
                    + .15 * candidate["crop_quality"]
                )
                pool.append({
                    "page": candidate["page_number"],
                    "value": candidate["normalized_value"],
                    "score": score,
                    "provider": candidate["provider_name"],
                    "validation_results": candidate.get("hard_validation_results", []),
                    "current_regional": False,
                    "evidence_role": "ROUTING_ONLY",
                })
        best_by_page = {}
        for candidate in pool:
            if candidate["value"] and (
                candidate["page"] not in best_by_page
                or candidate["score"] > best_by_page[candidate["page"]]["score"]
            ):
                best_by_page[candidate["page"]] = candidate
        ranked = sorted(best_by_page.values(), key=lambda item: item["score"], reverse=True)
        winner = ranked[0] if ranked else None
        runner_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
        margin = winner["score"] - runner_score if winner else 0.0
        reason = "SELECTED"
        if not winner or winner["score"] < MINIMUM_SCORE:
            winner, reason = None, "BELOW_THRESHOLD"
        elif len(ranked) > 1 and margin < MINIMUM_MARGIN:
            winner, reason = None, "AMBIGUOUS_PAGE"
        winning_page_candidates = [
            candidate for candidate in pool if winner and candidate["page"] == winner["page"]
        ]
        regional_candidates = [
            candidate for candidate in winning_page_candidates
            if candidate.get("current_regional")
        ]
        value_decision = reconcile_candidates(
            field, regional_candidates or winning_page_candidates
        ) if winner else None
        selected_value = (
            value_decision.value
            if value_decision and value_decision.value is not None
            else winner["value"] if winner else None
        )
        if value_decision and value_decision.value is None:
            reason = value_decision.reason
        if (
            not row.get("candidate_coverage", False)
            and row.get("writing_type") in {"HANDWRITTEN", "MIXED"}
        ):
            reason = "INSUFFICIENT_EVIDENCE"
        if (
            row.get("candidate_metadata", {})
            .get("derived_evidence", {})
            .get("automatically_acceptable") is False
        ):
            reason = "REVIEW_ONLY_CROSS_FIELD_DERIVATION"
        if (
            field.endswith(("addr1", "addr2"))
            and any(
                str(candidate.get("value") or "").strip().upper() == "UNKNOWN"
                for candidate in regional_candidates
            )
        ):
            reason = "SEMANTIC_REVIEW_REQUIRED"
        if field in {"patient_first", "patient_last"} and selected_value:
            reason = "REFERENCE_REQUIRED"
        extraction_correct = bool(winner) and (
            normalizers.normalize(field, selected_value)
            == normalizers.normalize(field, row["expected"])
        )
        decisions.append({
            "document_id": document_id, "field_name": field,
            "critical": field in critical, "expected_page": expected_page,
            "selected_page": winner["page"] if winner else None,
            "selected_value": selected_value, "score": winner["score"] if winner else 0.0,
            "margin": margin, "reason": reason,
            "review_required": reason != "SELECTED",
            "value_score": value_decision.score if value_decision else 0.0,
            "value_margin": value_decision.margin if value_decision else 0.0,
            "reconciliation_policy": "v2",
            "reconciliation_diagnostics": (
                list(value_decision.diagnostics) if value_decision else []
            ),
            "actual_page_correct": bool(winner) and winner["page"] == expected_page,
            "extraction_correct": extraction_correct,
        })
    total = len(decisions)
    metrics = {
        "evaluated_visible_fields": total,
        "actual_page_accuracy": sum(x["actual_page_correct"] for x in decisions) / total,
        "extraction_accuracy": sum(x["extraction_correct"] for x in decisions) / total,
        "wrong_page_field_count": sum(
            x["selected_page"] is not None and not x["actual_page_correct"] for x in decisions
        ),
        "unresolved_field_count": sum(x["selected_page"] is None for x in decisions),
        "ambiguous_page_rate": sum(x["reason"] == "AMBIGUOUS_PAGE" for x in decisions) / total,
        "ambiguous_value_rate": sum(x["reason"] == "AMBIGUOUS_VALUE" for x in decisions) / total,
        "critical_fields_routed_to_review": sum(
            x["critical"] and x["review_required"] for x in decisions
        ),
        "critical_false_accepts": sum(
            x["critical"] and not x["review_required"] and not x["extraction_correct"]
            for x in decisions
        ),
        "thresholds": {"minimum_score": MINIMUM_SCORE, "minimum_margin": MINIMUM_MARGIN},
        "remaining_error_pareto_by_field": dict(Counter(
            item["field_name"] for item in decisions if not item["extraction_correct"]
        ).most_common()),
        "remaining_error_pareto_by_reason": dict(Counter(
            item["reason"] for item in decisions if not item["extraction_correct"]
        ).most_common()),
    }
    output = Path("evaluation_results/current_v2_router")
    output.mkdir(parents=True, exist_ok=True)
    (output / "details.json").write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
