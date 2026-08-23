from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from packages.domain.enums import ClaimFormType
from packages.templates.registry import TemplateRegistry

from .build_manifest import RESULT_ROOT, ROOT
from .freeze import load_frozen_manifest
from .metrics import FIXED_ROUTES, STANDARD_FAMILIES, class_metrics, confusion, percentile, ratio
from .routing_benchmark import PHASE_ROOT


DOCS = ROOT / "docs"
CRITICAL_FIELDS = {"patient_name", "insured_id_number", "member_id", "provider_npi",
                   "total_charge", "principal_diagnosis", "diagnosis", "type_of_bill"}
ALIASES = {"patient_dob": "dob", "insured_id_number": "member_id", "federal_tax_id": "federal_tax_no",
           "patient_account_no": "account_no", "patient_control_number": "account_no",
           "patient_sex": "sex", "diagnosis_codes": "diagnosis", "insured_unique_id": "member_id",
           "provider_name_address": "provider_name", "billing_provider_info": "provider_name",
           "rel_code": "relationship"}


def _write(name: str, payload: Any) -> None:
    (PHASE_ROOT / name).write_text(json.dumps(payload, indent=2), "utf-8")


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper())


def _truth_top(family: str) -> str:
    if family in STANDARD_FAMILIES or family.startswith("CUSTOM_"):
        return "CLAIM"
    if family == "CLAIM_SUPPORT":
        return "CLAIM_SUPPORT"
    if family == "NON_CLAIM":
        return "NON_CLAIM"
    return "UNKNOWN"


def _route_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        row["expected_top_level"] = _truth_top(row["expected_family"])
        row["truth_standard_status"] = "STANDARD" if row["expected_family"] in STANDARD_FAMILIES else "NON_STANDARD"
        row["predicted_standard_status"] = "STANDARD" if row["predicted_family"] in STANDARD_FAMILIES else "NON_STANDARD"
    family_stats = class_metrics(rows, "expected_family", "predicted_family")
    top_stats = class_metrics(rows, "expected_top_level", "predicted_top_level")
    top_f1 = [ratio(2 * item["precision"] * item["recall"], item["precision"] + item["recall"])
              for item in top_stats.values()]
    truth_standard = [row for row in rows if row["expected_family"] in STANDARD_FAMILIES]
    predicted_standard = [row for row in rows if row["predicted_family"] in STANDARD_FAMILIES]
    nonstandard = [row for row in rows if row["expected_family"] not in STANDARD_FAMILIES]
    safe = [row for row in truth_standard if row["predicted_family"] == row["expected_family"] and
            row["predicted_processing_route"] in {"LAYOUT_STRUCTURED_EXTRACTOR", "SAFE_UNKNOWN"}]
    false_standard = [row for row in nonstandard if row["predicted_processing_route"] in FIXED_ROUTES]
    unverified = [row for row in rows if row["predicted_processing_route"] in FIXED_ROUTES and not (
        row.get("standard_verification") and row["standard_verification"].get("status") == "VERIFIED" and
        row["standard_verification"].get("eligible_for_fixed_extractor") is True)]
    wall = [row["latency_ms"]["total"] for row in rows]
    by_family = {}
    for family in sorted({row["expected_family"] for row in rows}):
        support = [row for row in rows if row["expected_family"] == family]
        by_family[family] = {"support": len(support),
            "exact_recall": ratio(sum(row["predicted_family"] == family for row in support), len(support)),
            "processing_route_accuracy": ratio(sum(row["predicted_processing_route"] == row["expected_processing_route"]
                                                    for row in support), len(support))}
    result = {"documents": len(rows),
        "overall_exact_routing_accuracy": ratio(sum(row["predicted_family"] == row["expected_family"] for row in rows), len(rows)),
        "processing_route_accuracy": ratio(sum(row["predicted_processing_route"] == row["expected_processing_route"] for row in rows), len(rows)),
        "top_level_taxonomy_accuracy": ratio(sum(row["predicted_top_level"] == row["expected_top_level"] for row in rows), len(rows)),
        "top_level_macro_f1": ratio(sum(top_f1), len(top_f1)),
        "standard_precision": ratio(sum(row["expected_family"] in STANDARD_FAMILIES for row in predicted_standard), len(predicted_standard)),
        "standard_recall": ratio(sum(row["predicted_family"] == row["expected_family"] for row in truth_standard), len(truth_standard)),
        "cms_precision": family_stats.get("CMS1500", {}).get("precision", 0.0),
        "cms_recall": family_stats.get("CMS1500", {}).get("recall", 0.0),
        "ub_precision": family_stats.get("UB04", {}).get("precision", 0.0),
        "ub_recall": family_stats.get("UB04", {}).get("recall", 0.0),
        "custom_professional_recall": family_stats.get("CUSTOM_PROFESSIONAL", {}).get("recall", 0.0),
        "custom_institutional_recall": family_stats.get("CUSTOM_INSTITUTIONAL", {}).get("recall", 0.0),
        "unknown_structured_recall": family_stats.get("UNKNOWN_STRUCTURED", {}).get("recall", 0.0),
        "claim_support_accuracy": family_stats.get("CLAIM_SUPPORT", {}).get("recall", 0.0),
        "non_claim_recall": family_stats.get("NON_CLAIM", {}).get("recall", 0.0),
        "unknown_unstructured_recall": family_stats.get("UNKNOWN_UNSTRUCTURED", {}).get("recall", 0.0),
        "unknown_unstructured_sample_size": sum(row["expected_family"] == "UNKNOWN_UNSTRUCTURED" for row in rows),
        "unknown_unstructured_status": "LOW_SAMPLE_SUPPORT",
        "safe_fallback_rate": ratio(len(safe), len(truth_standard)),
        "false_standard_authorization_rate": ratio(len(false_standard), len(nonstandard)),
        "false_standard_authorization_count": len(false_standard),
        "cms_to_ub_authorization_rate": ratio(sum(row["expected_family"] == "CMS1500" and
            row["predicted_processing_route"] == "UB_STANDARD_EXTRACTOR" for row in rows),
            sum(row["expected_family"] == "CMS1500" for row in rows)),
        "ub_to_cms_authorization_rate": ratio(sum(row["expected_family"] == "UB04" and
            row["predicted_processing_route"] == "CMS_STANDARD_EXTRACTOR" for row in rows),
            sum(row["expected_family"] == "UB04" for row in rows)),
        "unverified_fixed_authorization_count": len(unverified),
        "route_extractor_firewall_violations": len(unverified) + len(false_standard),
        "latency_ms": {"p50": percentile(wall, .50), "p95": percentile(wall, .95),
                       "p99": percentile(wall, .99), "mean": ratio(sum(wall), len(wall))},
        "by_family": by_family}
    return result


def _splits(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {"all": rows, "tuning_permitted": [row for row in rows if row["tuning_allowed"]],
            "observation_only": [row for row in rows if not row["tuning_allowed"]]}


def _family_source(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    keys = sorted({(row["expected_family"], row["source_dataset"]) for row in rows})
    for family, source in keys:
        subset = [row for row in rows if row["expected_family"] == family and row["source_dataset"] == source]
        latency = [row["latency_ms"]["total"] for row in subset]
        truth_standard = family in STANDARD_FAMILIES
        output.append({"family": family, "source_dataset": source, "count": len(subset),
            "routing_accuracy": ratio(sum(row["predicted_family"] == family for row in subset), len(subset)),
            "processing_route_accuracy": ratio(sum(row["predicted_processing_route"] == row["expected_processing_route"]
                                                   for row in subset), len(subset)),
            "false_standard_authorizations": sum(not truth_standard and
                row["predicted_processing_route"] in FIXED_ROUTES for row in subset),
            "safe_fallbacks": sum(truth_standard and row["predicted_family"] == family and
                row["predicted_processing_route"] in {"LAYOUT_STRUCTURED_EXTRACTOR", "SAFE_UNKNOWN"} for row in subset),
            "latency_ms": {"p50": percentile(latency, .50), "p95": percentile(latency, .95),
                           "p99": percentile(latency, .99)}})
    return output


def _verifier(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for family in ("CMS1500", "UB04"):
        positives = [row for row in rows if row["expected_family"] == family]
        negatives = [row for row in rows if row["expected_family"] != family]
        status = lambda row: row["direct_verification"][family]["status"]
        tp = sum(status(row) == "VERIFIED" for row in positives)
        fp = sum(status(row) == "VERIFIED" for row in negatives)
        output[family] = {"positive_pages": len(positives), "hard_negative_pages": len(negatives),
            "precision": ratio(tp, tp + fp), "recall": ratio(tp, len(positives)),
            "false_verification_rate": ratio(fp, len(negatives)),
            "not_verified_rate": ratio(sum(status(row) == "NOT_VERIFIED" for row in positives), len(positives)),
            "ambiguous_rate": ratio(sum(status(row) == "AMBIGUOUS" for row in positives), len(positives)),
            "true_verified": tp, "false_verified": fp,
            "by_dataset": {}}
        for source in sorted({row["source_dataset"] for row in rows}):
            source_rows = [row for row in rows if row["source_dataset"] == source]
            source_pos = [row for row in source_rows if row["expected_family"] == family]
            source_neg = [row for row in source_rows if row["expected_family"] != family]
            source_tp = sum(status(row) == "VERIFIED" for row in source_pos)
            source_fp = sum(status(row) == "VERIFIED" for row in source_neg)
            output[family]["by_dataset"][source] = {"positive_pages": len(source_pos),
                "negative_pages": len(source_neg), "precision": ratio(source_tp, source_tp + source_fp),
                "recall": ratio(source_tp, len(source_pos)),
                "false_verification_rate": ratio(source_fp, len(source_neg)),
                "not_verified_rate": ratio(sum(status(row) == "NOT_VERIFIED" for row in source_pos), len(source_pos)),
                "ambiguous_rate": ratio(sum(status(row) == "AMBIGUOUS" for row in source_pos), len(source_pos))}
    return output


def _error_category(row: dict[str, Any]) -> str:
    truth, predicted = row["expected_family"], row["predicted_family"]
    if truth in STANDARD_FAMILIES and predicted in STANDARD_FAMILIES and truth != predicted:
        return "CMS_UB_CONFUSION"
    if truth in STANDARD_FAMILIES and predicted == truth and row["predicted_processing_route"] != row["expected_processing_route"]:
        if row["predicted_processing_route"] in {"LAYOUT_STRUCTURED_EXTRACTOR", "SAFE_UNKNOWN"}:
            return "SAFE_FALLBACK"
        return "STANDARD_VERIFICATION_FAILURE"
    if truth in STANDARD_FAMILIES and predicted != truth:
        evidence = row["routing_evidence"]
        if evidence.get("weighted_anchor_coverage", {}).get(truth, 0) < .20:
            return "ANCHOR_MISS"
        if evidence.get("anchor_geometry_score", {}).get(truth, 0) < .45:
            return "GEOMETRY_FAILURE"
        if evidence.get("standard_structure", {}).get(truth, 0) < .45:
            return "STRUCTURE_FAILURE"
        if evidence.get("margin", 0) < .05:
            return "MARGIN_FAILURE"
        return "CMS_NOMINATION_FAILURE" if truth == "CMS1500" else "UB_NOMINATION_FAILURE"
    if truth.startswith("CUSTOM_"):
        return "CUSTOM_STRUCTURE_FAILURE"
    if truth == "CLAIM_SUPPORT":
        return "TOP_LEVEL_TAXONOMY_FAILURE"
    if truth == "NON_CLAIM":
        return "NON_CLAIM_FAILURE"
    if truth.startswith("UNKNOWN_"):
        return "UNKNOWN_FALLBACK"
    if row.get("expected_top_level") != row.get("predicted_top_level"):
        return "TOP_LEVEL_TAXONOMY_FAILURE"
    if row.get("truth_standard_status") != row.get("predicted_standard_status"):
        return "STANDARD_NON_STANDARD_FAILURE"
    return "OTHER"


def _pareto(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    for row in rows:
        if row["predicted_family"] == row["expected_family"] and row["predicted_processing_route"] == row["expected_processing_route"]:
            continue
        errors.append({"document_id": row["document_id"], "expected_family": row["expected_family"],
            "predicted_family": row["predicted_family"], "source_dataset": row["source_dataset"],
            "tuning_allowed": row["tuning_allowed"], "category": _error_category(row),
            "expected_processing_route": row["expected_processing_route"],
            "predicted_processing_route": row["predicted_processing_route"]})
    groups = defaultdict(list)
    for error in errors:
        groups[error["category"]].append(error)
    cumulative = 0
    summary = []
    for category, items in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        cumulative += len(items)
        summary.append({"category": category, "count": len(items), "percent_total_errors": ratio(len(items), len(errors)),
            "cumulative_percent": ratio(cumulative, len(errors)),
            "families_affected": sorted({item["expected_family"] for item in items}),
            "datasets_affected": sorted({item["source_dataset"] for item in items}),
            "tuning_permitted_count": sum(item["tuning_allowed"] for item in items),
            "observation_only_count": sum(not item["tuning_allowed"] for item in items)})
    return {"total_errors": len(errors), "categories": summary, "errors": errors}


def _best_fields(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    best = {}
    for field in document["fields"]:
        key = field["field_name"]
        if key not in best or field["confidence"] > best[key]["confidence"]:
            best[key] = field
    return best


def _extraction(manifest_by_id: dict[str, Any], route_by_id: dict[str, Any]) -> tuple[dict, dict, dict, dict]:
    details = [json.loads(line) for line in (RESULT_ROOT / "extraction_details.jsonl").read_text("utf-8").splitlines()]
    # Use exactly the deterministic 30-page selection emitted by the current metrics.
    selected_ids = []
    for family in ("CMS1500", "UB04"):
        public = sorted([row for row in manifest_by_id.values() if row.expected_family == family and
                         row.source_dataset.startswith("SYNTHETIC_PUBLIC")], key=lambda row: (row.quality_bucket, row.document_id))[:12]
        observed = sorted([row for row in manifest_by_id.values() if row.expected_family == family and
                           row.source_dataset == "PRODUCTION_HOLDOUT_V2_REPRESENTATIVE"],
                          key=lambda row: (row.quality_bucket, row.document_id))[:3]
        selected_ids.extend(row.document_id for row in public + observed)
    detail_by_id = {row["document_id"]: row for row in details}
    documents = [detail_by_id[document_id] for document_id in selected_ids]
    fields = [(document, field) for document in documents for field in _best_fields(document).values()]
    registry = TemplateRegistry.load_from_directory()
    required = {"CMS1500": set(registry.latest_for_form_type(ClaimFormType.CMS1500).required_fields),
                "UB04": set(registry.latest_for_form_type(ClaimFormType.UB04).required_fields)}
    by_family = {}
    for family in ("CMS1500", "UB04"):
        family_docs = [doc for doc in documents if doc["expected_family"] == family]
        family_fields = [field for doc, field in fields if doc["expected_family"] == family]
        required_fields = [field for field in family_fields if field["source_field_name"] in required[family]]
        critical = [field for field in family_fields if field["field_name"] in CRITICAL_FIELDS]
        checkbox = [field for field in family_fields if field["field_name"] in {"sex", "relationship"}]
        perfect = sum(all(field["final_exact"] for field in _best_fields(doc).values()) for doc in family_docs)
        latency = [doc["latency_ms"]["total"] for doc in family_docs]
        by_family[family] = {"documents": len(family_docs), "fields": len(family_fields),
            "field_exact_accuracy": ratio(sum(field["final_exact"] for field in family_fields), len(family_fields)),
            "critical_field_accuracy": ratio(sum(field["final_exact"] for field in critical), len(critical)),
            "required_field_accuracy": ratio(sum(field["final_exact"] for field in required_fields), len(required_fields)),
            "crop_correctness": ratio(sum(field["crop_correct"] for field in family_fields), len(family_fields)),
            "ocr_accuracy_given_correct_crop": ratio(sum(field["final_exact"] for field in family_fields if field["crop_correct"]),
                                                       sum(field["crop_correct"] for field in family_fields)),
            "normalization_accuracy": ratio(sum(field["normalization_correct"] for field in family_fields), len(family_fields)),
            "parser_accuracy": ratio(sum(field["parser_success"] for field in family_fields), len(family_fields)),
            "checkbox_accuracy": ratio(sum(field["final_exact"] for field in checkbox), len(checkbox)) if checkbox else "NOT_MEASURABLE",
            "safe_field_coverage": ratio(sum(field["auto_accepted"] and field["final_exact"] for field in family_fields), len(family_fields)),
            "field_hitl_estimate": ratio(sum(not field["auto_accepted"] for field in family_fields), len(family_fields)),
            "claim_perfect_rate": ratio(perfect, len(family_docs)),
            "latency_ms": {"p50": percentile(latency, .50), "p95": percentile(latency, .95),
                           "p99": percentile(latency, .99)}}
    tables = [doc["service_lines"] for doc in documents if doc.get("service_lines")]
    truth_rows = sum(table["truth_rows"] for table in tables)
    by_family["UB04"].update({"revenue_code_accuracy": 0.0 if truth_rows else "NOT_MEASURABLE",
        "hcpcs_accuracy": 0.0 if truth_rows else "NOT_MEASURABLE", "service_date_accuracy": 0.0 if truth_rows else "NOT_MEASURABLE",
        "units_accuracy": 0.0 if truth_rows else "NOT_MEASURABLE", "charge_accuracy": 0.0 if truth_rows else "NOT_MEASURABLE",
        "service_line_row_reconstruction_accuracy": ratio(sum(table["row_detection_correct"] for table in tables), len(tables)),
        "column_assignment_accuracy": 0.0 if truth_rows else "NOT_MEASURABLE",
        "claim_total_reconciliation_accuracy": 0.0 if truth_rows else "NOT_MEASURABLE",
        "truth_service_rows": truth_rows, "detected_service_rows": sum(table["detected_rows"] for table in tables)})
    layout = json.loads((PHASE_ROOT / "layout_extraction_metrics.json").read_text("utf-8"))
    custom = {"documents": layout["documents"], "field_label_value_accuracy": layout["field_exact_match"],
        "table_extraction_accuracy": "NOT_MEASURABLE", "structured_region_accuracy": "NOT_MEASURABLE",
        "schema_recovery_accuracy": layout["structured_route_recall"],
        "unsupported_field_count": 0, "docling_required_rate": "NOT_MEASURABLE",
        "layout_failure_rate": 1 - layout["structured_route_recall"], "latency_p95_ms": layout["p95_latency_ms"]}
    all_fields = [field for _, field in fields]
    extraction = {"evidence_class": "ENGINEERING_BENCHMARK_ONLY", "truth_route_forced": True,
        "sample_design": "30 deterministic pages: per family 12 public synthetic + 3 observation-only representative",
        "documents": len(documents), "fields": len(all_fields), "CMS1500": by_family["CMS1500"],
        "UB04": by_family["UB04"], "CUSTOM_STRUCTURED": custom,
        "overall_field_accuracy": ratio(sum(field["final_exact"] for field in all_fields), len(all_fields)),
        "critical_field_accuracy": ratio(sum(field["final_exact"] for field in all_fields if field["field_name"] in CRITICAL_FIELDS),
                                         sum(field["field_name"] in CRITICAL_FIELDS for field in all_fields)),
        "false_accepts": sum(field["auto_accepted"] and not field["final_exact"] for field in all_fields),
        "critical_false_accepts": sum(field["auto_accepted"] and not field["final_exact"] and
                                      field["field_name"] in CRITICAL_FIELDS for field in all_fields)}
    crop_fields = [field for _, field in fields if field.get("crop_iou") is not None]
    registration = {"documents": len(documents), "registration_configured": 0, "registration_success": 0,
        "registration_success_rate": 0.0, "registration_confidence_distribution": "NOT_MEASURABLE",
        "crop_fields_with_truth": len(crop_fields),
        "crop_correctness": ratio(sum(field["crop_correct"] for field in crop_fields), len(crop_fields)),
        "roi_too_tight": "NOT_MEASURABLE", "roi_too_wide": "NOT_MEASURABLE",
        "label_contamination": sum(bool(field["raw"] and _norm(field["expected"]) in _norm(field["raw"]) and
                                         not field["raw_exact"]) for field in crop_fields),
        "wrong_field_crop": "NOT_MEASURABLE", "empty_crop": sum(not str(field["raw"]).strip() for field in crop_fields),
        "by_source": {}}
    for source in sorted({doc["source_dataset"] for doc in documents}):
        source_fields = [field for doc, field in fields if doc["source_dataset"] == source and field.get("crop_iou") is not None]
        registration["by_source"][source] = {"fields": len(source_fields),
            "crop_correctness": ratio(sum(field["crop_correct"] for field in source_fields), len(source_fields))}

    attribution = Counter()
    field_outcomes = []
    correct = critical_total = critical_correct = 0
    perfect_documents = 0
    hitl = 0
    latency = []
    for doc in documents:
        record = manifest_by_id[doc["document_id"]]
        route = route_by_id[doc["document_id"]]
        best = _best_fields(doc)
        doc_correct = True
        truth = {key: value for key, value in record.truth_fields.items() if key != "service_lines"}
        for field_name, expected in truth.items():
            field = best.get(field_name)
            route_correct = route["predicted_processing_route"] == record.expected_processing_route
            exact = bool(field) and field["final_exact"] and route_correct
            primary = None
            if exact:
                correct += 1
            elif not route_correct:
                primary = ("VERIFICATION" if route["predicted_family"] == record.expected_family and
                           route.get("standard_verification") and
                           route["standard_verification"].get("status") != "VERIFIED" else "ROUTING")
            elif field is None:
                primary = "UNSUPPORTED"
            elif not field["crop_correct"]:
                primary = "ROI_CROP"
            elif not field["parser_success"] or not field["raw_exact"]:
                primary = "OCR"
            elif not field["normalization_correct"]:
                primary = "NORMALIZATION"
            else:
                primary = "PARSER"
            if primary:
                attribution[primary] += 1
                doc_correct = False
            critical = field_name in CRITICAL_FIELDS
            critical_total += critical
            critical_correct += int(critical and exact)
            hitl += int(field is None or not field["auto_accepted"])
            field_outcomes.append({"document_id": doc["document_id"], "field_name": field_name,
                                   "correct": exact, "primary_loss_layer": primary})
        if record.truth_fields.get("service_lines"):
            missing_rows = len(record.truth_fields["service_lines"]) - (doc.get("service_lines") or {}).get("detected_rows", 0)
            if missing_rows > 0:
                attribution["TABLE_RECONSTRUCTION"] += missing_rows
                doc_correct = False
        perfect_documents += doc_correct
        latency.append(route["latency_ms"]["total"] + doc["latency_ms"]["total"])
    total_truth = len(field_outcomes)
    errors = sum(attribution.values())
    end_to_end = {"documents": len(documents), "truth_fields": total_truth,
        "field_accuracy": ratio(correct, total_truth), "critical_field_accuracy": ratio(critical_correct, critical_total),
        "correct_fields": correct, "perfect_documents": perfect_documents,
        "perfect_document_rate": ratio(perfect_documents, len(documents)),
        "wrong_route_loss": attribution["ROUTING"], "verification_loss": attribution["VERIFICATION"],
        "extraction_loss": sum(attribution[key] for key in ("REGISTRATION", "ROI_CROP", "OCR", "NORMALIZATION", "PARSER", "TABLE_RECONSTRUCTION")),
        "unsupported_loss": attribution["UNSUPPORTED"], "hitl_abstention_rate": ratio(hitl, total_truth),
        "counterfactual_latency_ms": {"p50": percentile(latency, .50), "p95": percentile(latency, .95),
                                      "p99": percentile(latency, .99)},
        "normal_pipeline_latency": "NOT_MEASURABLE_FOR_WRONG_ROUTE_LAYOUT_OUTPUTS",
        "field_outcomes": field_outcomes}
    error_attribution = {"total_attributed_errors": errors,
        "layers": {key: {"count": attribution[key], "percent": ratio(attribution[key], errors)} for key in (
            "ROUTING", "VERIFICATION", "REGISTRATION", "ROI_CROP", "OCR", "NORMALIZATION", "PARSER",
            "TABLE_RECONSTRUCTION", "UNSTRUCTURED_EXTRACTION", "UNSUPPORTED", "GROUND_TRUTH_OR_FIXTURE", "UNKNOWN")}}
    return extraction, registration, end_to_end, error_attribution


def _ocr() -> dict[str, Any]:
    trials = [json.loads(line) for line in (PHASE_ROOT / "ocr_trials.jsonl").read_text("utf-8").splitlines()]
    for row in trials:
        row["dataset_class"] = row["document_id"].split(":", 1)[0]
        row["accuracy_given_correct_crop"] = row["exact"]
    groups = defaultdict(list)
    for row in trials:
        groups[(row["document_id"], row["field_name"])].append(row)
    agreements = false_agreements = 0
    for items in groups.values():
        values = {_norm(item["observed"]) for item in items}
        if len(values) == 1:
            agreements += 1
            false_agreements += int(not items[0]["exact"])
    current = json.loads((PHASE_ROOT / "ocr_by_field.json").read_text("utf-8"))
    current["agreement"] = {"crop_groups": len(groups), "all_engine_agreement_rate": ratio(agreements, len(groups)),
                            "false_agreement_rate": ratio(false_agreements, len(groups))}
    current["by_dataset_class"] = {}
    for dataset in sorted({row["dataset_class"] for row in trials}):
        items = [row for row in trials if row["dataset_class"] == dataset]
        current["by_dataset_class"][dataset] = {"trials": len(items),
            "exact_accuracy": ratio(sum(item["exact"] for item in items), len(items)),
            "mean_cer": ratio(sum(item["cer"] for item in items), len(items)),
            "p95_latency_ms": percentile((item["latency_ms"] for item in items), .95),
            "accuracy_given_correct_crop": ratio(sum(item["accuracy_given_correct_crop"] for item in items), len(items))}
    return current


def _docs(routing: dict, verification: dict, extraction: dict, end: dict,
          attribution: dict, pareto: dict, performance: dict, experiment: dict | None) -> None:
    all_metrics = routing["splits"]["all"]
    def pct(value): return f"{100*value:.2f}%" if isinstance(value, (int, float)) else str(value)
    split_rows = "\n".join(f"| {name} | {values['documents']} | {pct(values['overall_exact_routing_accuracy'])} | {pct(values['processing_route_accuracy'])} | {pct(values['cms_recall'])} | {pct(values['ub_recall'])} | {pct(values['false_standard_authorization_rate'])} |"
                           for name, values in routing["splits"].items())
    (DOCS / "CDP_PHASE7A13_ENGINEERING_ACCURACY_REPORT.md").write_text(f"""# CDP Phase 7A.13B Engineering Accuracy Report

`ENGINEERING_BENCHMARK_ONLY`; no production-promotion authority. Frozen benchmark: 1,230 unique pages (430 tuning-permitted, 800 observation-only), manifest `{routing['manifest_sha256']}`.

| Population | Pages | Exact route | Processing route | CMS recall | UB recall | False standard |
|---|---:|---:|---:|---:|---:|---:|
{split_rows}

Truth-route standard extraction is {pct(extraction['overall_field_accuracy'])}; critical accuracy is {pct(extraction['critical_field_accuracy'])}. End-to-end field accuracy is {pct(end['field_accuracy'])}. Primary decision: `{routing['decision']}`. UNKNOWN_UNSTRUCTURED has five pages, status `LOW_SAMPLE_SUPPORT`, and is not a release gate.

Experiment 1: `{(experiment or {}).get('decision', 'PENDING')}`. Production runtime remained unchanged.
""", "utf-8")
    matrices = json.loads((PHASE_ROOT / "confusion_matrix.json").read_text("utf-8"))
    (DOCS / "CDP_PHASE7A13_ROUTING_CONFUSION_MATRIX.md").write_text(
        "# CDP Phase 7A.13 Routing Confusion Matrix\n\nFull JSON matrices: `evaluation_results/phase7a13/confusion_matrix.json`.\n\n" +
        "```json\n" + json.dumps(matrices, indent=2) + "\n```\n", "utf-8")
    pareto_rows = "\n".join(f"| {item['category']} | {item['count']} | {pct(item['percent_total_errors'])} | {pct(item['cumulative_percent'])} | {item['tuning_permitted_count']} | {item['observation_only_count']} |"
                               for item in pareto["categories"])
    (DOCS / "CDP_PHASE7A13_ROUTING_ERROR_PARETO.md").write_text(f"""# CDP Phase 7A.13 Routing Error Pareto

| Category | Count | Share | Cumulative | Tuning | Observation |
|---|---:|---:|---:|---:|---:|
{pareto_rows}
""", "utf-8")
    (DOCS / "CDP_PHASE7A13_VERIFIER_REPORT.md").write_text(
        "# CDP Phase 7A.13 Verifier Report\n\n```json\n" + json.dumps(verification, indent=2) + "\n```\n", "utf-8")
    (DOCS / "CDP_PHASE7A13_EXTRACTION_GIVEN_ROUTE.md").write_text(
        "# CDP Phase 7A.13 Extraction Given Truth Route\n\n```json\n" + json.dumps(extraction, indent=2) + "\n```\n", "utf-8")
    (DOCS / "CDP_PHASE7A13_END_TO_END.md").write_text(
        "# CDP Phase 7A.13 End-to-End\n\n```json\n" + json.dumps({k:v for k,v in end.items() if k != 'field_outcomes'}, indent=2) + "\n```\n", "utf-8")
    (DOCS / "CDP_PHASE7A13_ERROR_ATTRIBUTION.md").write_text(
        "# CDP Phase 7A.13 Error Attribution\n\n```json\n" + json.dumps(attribution, indent=2) + "\n```\n", "utf-8")
    (DOCS / "CDP_PHASE7A13_PERFORMANCE.md").write_text(
        "# CDP Phase 7A.13 Performance\n\n```json\n" + json.dumps(performance, indent=2) + "\n```\n", "utf-8")
    (DOCS / "CDP_PHASE7A13_EXPERIMENT_1.md").write_text(
        "# CDP Phase 7A.13 Experiment 1\n\n```json\n" + json.dumps(experiment or {"status":"PENDING_BASELINE"}, indent=2) + "\n```\n", "utf-8")


def run(experiment: dict | None = None) -> dict[str, Any]:
    manifest = load_frozen_manifest()
    rows_by_id = {json.loads(line)["document_id"]: json.loads(line) for line in
                  (RESULT_ROOT / "routing_details.jsonl").read_text("utf-8").splitlines()}
    missing = [record.document_id for record in manifest.records if record.document_id not in rows_by_id]
    if missing:
        raise RuntimeError(f"routing baseline incomplete: {len(missing)} frozen pages missing")
    rows = [rows_by_id[record.document_id] for record in manifest.records]
    split_rows = _splits(rows)
    split_metrics = {name: _route_metrics(items) for name, items in split_rows.items()}
    routing = {**split_metrics["all"], "splits": split_metrics,
               "manifest_sha256": manifest.manifest_sha256,
               "evidence_class": "ENGINEERING_BENCHMARK_ONLY"}
    routing["by_quality"] = {}
    for quality in sorted({row["quality_bucket"] for row in rows}):
        routing["by_quality"][quality] = _route_metrics(
            [row for row in rows if row["quality_bucket"] == quality])
    family_source = _family_source(rows)
    by_dataset = {}
    for source in sorted({row["source_dataset"] for row in rows}):
        by_dataset[source] = _route_metrics([row for row in rows if row["source_dataset"] == source])
    matrices = {"top_level_taxonomy": confusion(rows, "expected_top_level", "predicted_top_level"),
        "standard_family_nomination": confusion([
            {**row, "truth_nomination": row["expected_family"] if row["expected_family"] in STANDARD_FAMILIES else "NON_STANDARD",
             "predicted_nomination": row["predicted_family"] if row["predicted_family"] in STANDARD_FAMILIES else "NON_STANDARD"}
            for row in rows], "truth_nomination", "predicted_nomination"),
        "final_processing_route": confusion(rows, "expected_processing_route", "predicted_processing_route")}
    pareto = _pareto(rows)
    verification = {name: _verifier(items) for name, items in split_rows.items()}
    manifest_by_id = {record.document_id: record for record in manifest.records}
    extraction, registration, end, attribution = _extraction(manifest_by_id, rows_by_id)
    ocr = _ocr()
    performance = json.loads((PHASE_ROOT / "performance.json").read_text("utf-8"))
    performance["classification_nomination_verification_latency_ms"] = split_metrics["all"]["latency_ms"]
    performance["registration_ocr_normalization_latency_ms"] = {
        family: extraction[family]["latency_ms"] for family in ("CMS1500", "UB04")}
    performance["table_reconstruction"] = {"truth_rows": extraction["UB04"]["truth_service_rows"],
        "detected_rows": extraction["UB04"]["detected_service_rows"]}
    performance["mean_cpu_seconds_per_page"] = "NOT_MEASURABLE_ON_WINDOWS_SUBPROCESS_TREE"
    performance["mean_cpu_seconds_per_page_note"] = (
        "Tesseract executes as a child process and the Windows host did not expose child CPU accounting; "
        "stage wall latency is measured and no CPU value is fabricated.")
    performance["memory"] = "NOT_MEASURABLE_WITHOUT_A_CHILD_PROCESS_PEAK_SAMPLER"
    performance["nomination_latency"] = "INCLUDED_IN_ROUTER_NOT_SEPARATELY_INSTRUMENTED"
    performance["normalization_latency"] = "INCLUDED_IN_FIELD_EXTRACTION_NOT_SEPARATELY_INSTRUMENTED"
    performance["cloud_cost_usd"] = 0.0
    processing_good = split_metrics["all"]["processing_route_accuracy"] >= .95
    extraction_good = extraction["overall_field_accuracy"] >= .95
    nomination_good = min(split_metrics["all"]["cms_recall"], split_metrics["all"]["ub_recall"]) >= .95
    verifier_good = min(verification["all"]["CMS1500"]["recall"], verification["all"]["UB04"]["recall"]) >= .95
    if not processing_good and not extraction_good:
        decision = "MULTIPLE_BOTTLENECKS"
    elif not processing_good and nomination_good and not verifier_good:
        decision = "STANDARD_VERIFICATION_BOTTLENECK"
    elif not processing_good:
        decision = "ROUTING_BOTTLENECK"
    elif not extraction_good:
        decision = "EXTRACTION_BOTTLENECK"
    else:
        decision = "NO_MAJOR_ACCURACY_BOTTLENECK"
    routing["decision"] = decision
    secondary = []
    if not nomination_good: secondary.append("STANDARD_NOMINATION")
    if not verifier_good: secondary.append("STANDARD_VERIFICATION")
    if not extraction_good: secondary.append("EXTRACTION")
    if split_metrics["all"]["latency_ms"]["p95"] > 1000: secondary.append("ROUTING_LATENCY")
    decision_payload = {"primary_bottleneck": decision, "secondary_bottlenecks": secondary,
        "evidence_class": "ENGINEERING_BENCHMARK_ONLY", "production_promotion_authority": False,
        "experiment_1": (experiment or {}).get("decision", "PENDING")}
    for name, payload in (("routing_metrics.json", routing), ("routing_by_dataset.json", by_dataset),
                          ("routing_by_family_source.json", family_source), ("confusion_matrix.json", matrices),
                          ("error_pareto.json", pareto), ("verification_metrics.json", verification),
                          ("extraction_metrics.json", extraction), ("end_to_end_metrics.json", end),
                          ("error_attribution.json", attribution), ("ocr_by_field.json", ocr),
                          ("registration_metrics.json", registration), ("performance.json", performance),
                          ("decision.json", decision_payload)):
        _write(name, payload)
    page_results = []
    for row in rows:
        safe_fallback = (row["expected_family"] in STANDARD_FAMILIES and
                         row["predicted_family"] == row["expected_family"] and
                         row["predicted_processing_route"] in {"LAYOUT_STRUCTURED_EXTRACTOR", "SAFE_UNKNOWN"})
        page_results.append({"document_id": row["document_id"], "page_id": row["page_id"],
            "truth_family": row["expected_family"], "predicted_top_level_taxonomy": row["predicted_top_level"],
            "truth_standard": row["expected_family"] in STANDARD_FAMILIES,
            "predicted_standard": row["predicted_family"] in STANDARD_FAMILIES,
            "truth_standard_family": row["expected_family"] if row["expected_family"] in STANDARD_FAMILIES else None,
            "nominated_family": row["predicted_family"] if row["predicted_family"] in STANDARD_FAMILIES else None,
            "verification_status": ((row.get("standard_verification") or {}).get("status")),
            "final_processing_route": row["predicted_processing_route"],
            "expected_processing_route": row["expected_processing_route"],
            "safe_fallback": safe_fallback, "latency_ms": row["latency_ms"],
            "reason_codes": row["route_reason_codes"],
            "tuning_status": "TUNING_PERMITTED" if row["tuning_allowed"] else "OBSERVATION_ONLY"})
    (PHASE_ROOT / "routing_page_results.jsonl").write_text(
        "\n".join(json.dumps(item, separators=(",", ":")) for item in page_results) + "\n", "utf-8")
    _docs(routing, verification, extraction, end, attribution, pareto, performance, experiment)
    return {"routing": routing, "verification": verification, "extraction": extraction,
            "end_to_end": end, "error_attribution": attribution, "pareto": pareto,
            "decision": decision_payload}


if __name__ == "__main__":
    result = run()
    print(json.dumps({"routing": result["routing"]["splits"], "extraction": result["extraction"],
                      "end_to_end": {key:value for key,value in result["end_to_end"].items() if key != "field_outcomes"},
                      "decision": result["decision"]}, indent=2))
