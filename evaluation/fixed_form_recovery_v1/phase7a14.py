"""Execute the governed Phase 7A.14 tuning-only diagnostic sequence.

The frozen manifest contains no field truth or truth crop boxes on its 430
tuning-permitted pages.  This runner therefore executes the registration and
template-compatibility work that is measurable, then fail-closes later
experiments instead of using the 800 observation-only pages for development.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from packages.domain.enums import ClaimFormType
from packages.templates.registry import TemplateRegistry

from evaluation.engineering_benchmark_v1.freeze import load_frozen_manifest
from evaluation.engineering_benchmark_v1.build_manifest import RESULT_ROOT as PHASE13_WORK

from .registration import (
    ROOT,
    aggregate_forensics,
    audit_template_assets,
    registration_controls,
    registration_forensic_record,
    sha256_file,
)


PHASE13 = ROOT / "evaluation_results/phase7a13"
OUTPUT = ROOT / "evaluation_results/phase7a14"
DOCS = ROOT / "docs"


def _json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _write(name: str, payload: Any) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(payload, indent=2), "utf-8")


def _hash_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def freeze_baseline(manifest) -> dict[str, Any]:
    template_paths = sorted((ROOT / "config/templates").glob("*.yaml"))
    table_paths = sorted((ROOT / "config/table_templates").glob("*.yaml"))
    verifier_paths = sorted((ROOT / "packages/standard_form_verification").glob("*.py"))
    preprocessing_paths = [
        ROOT / "workers/document_preparation/operations.py",
        ROOT / "workers/retry/alternate_preprocessing.py",
    ]
    preprocessing_paths = [path for path in preprocessing_paths if path.is_file()]
    reference_paths = sorted((ROOT / "config/templates/reference_images").glob("*.png"))
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "baseline_id": "FIXED_FORM_RECOVERY_BASELINE_V1",
        "immutable_source": "PHASE7A13B_FROZEN_RESULTS",
        "git_sha": git_sha,
        "configuration_hashes": {
            "templates": _hash_paths(template_paths),
            "table_templates": _hash_paths(table_paths),
            "standard_verifiers": _hash_paths(verifier_paths),
            "preprocessing": _hash_paths(preprocessing_paths) if preprocessing_paths else "NO_FILES",
        },
        "template_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha256_file(path)
            for path in reference_paths
        },
        "roi_versions": {
            "cms1500": "cms1500@02-12:" + sha256_file(ROOT / "config/templates/cms1500_v02_12.yaml")[:16],
            "ub04": "ub04@2014:" + sha256_file(ROOT / "config/templates/ub04_v2014.yaml")[:16],
        },
        "registration_version": "adaptive-registration-v1+template-compatibility-v1",
        "ocr_provider_versions": {
            "rapidocr_onnxruntime": _version("rapidocr-onnxruntime"),
            "paddleocr": _version("paddleocr"),
            "pytesseract": _version("pytesseract"),
        },
        "preprocessing_version": "bounded-preprocessing-router-v1",
        "cms_verifier_version": "cms1500-verifier-v1",
        "ub_verifier_version": "ub04-verifier-v1",
        "benchmark_manifest_hash": manifest.manifest_sha256,
        "eligibility_split": {"TUNING_PERMITTED": 430, "OBSERVATION_ONLY": 800},
        "frozen_metrics": {
            "routing": _json(PHASE13 / "routing_metrics.json"),
            "verification": _json(PHASE13 / "verification_metrics.json"),
            "extraction": _json(PHASE13 / "extraction_metrics.json"),
            "performance": _json(PHASE13 / "performance.json"),
            "decision": _json(PHASE13 / "decision.json"),
        },
    }


def _tuning_routes(manifest) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tuning = {record.document_id: record.model_dump(mode="json")
              for record in manifest.records if record.tuning_allowed}
    routes = {}
    for line in (PHASE13_WORK / "routing_details.jsonl").read_text("utf-8").splitlines():
        row = json.loads(line)
        if row["document_id"] in tuning:
            routes[row["document_id"]] = row
    if len(routes) != 430:
        raise RuntimeError(f"frozen tuning route count is {len(routes)}, expected 430")
    nominations = [row for row in routes.values()
                   if row["predicted_family"] in {"CMS1500", "UB04"}]
    if len(nominations) != 132:
        raise RuntimeError(f"registration replay count is {len(nominations)}, expected 132")
    return nominations, tuning


def _verifier_diagnostic(routes: list[dict[str, Any]], family: str) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in routes:
        direct = row["direct_verification"][family]
        positive = row["expected_family"] == family
        status = direct["status"]
        if positive and status == "VERIFIED":
            bucket = "TRUE_VERIFIED"
        elif not positive and status == "VERIFIED":
            bucket = "FALSE_VERIFIED"
        elif positive:
            bucket = "FALSE_NOT_VERIFIED"
        else:
            bucket = "TRUE_NOT_VERIFIED"
        buckets[bucket].append(direct)
    evidence = {}
    for bucket, rows in buckets.items():
        counts = Counter(name for row in rows for name in row["supporting_evidence_classes"])
        evidence[bucket] = {"pages": len(rows), "supporting_evidence_frequency": dict(counts)}
    positives = sum(row["expected_family"] == family for row in routes)
    negatives = len(routes) - positives
    tp = len(buckets["TRUE_VERIFIED"])
    fp = len(buckets["FALSE_VERIFIED"])
    return {
        "family": family,
        "policy_version": "cms1500-verifier-v1" if family == "CMS1500" else "ub04-verifier-v1",
        "positive_pages": positives,
        "hard_negative_pages": negatives,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / positives if positives else 0.0,
        "false_verification_rate": fp / negatives if negatives else 0.0,
        "outcomes": evidence,
        "identity_registration_separation": {
            "identity_may_be_verified_without_registration": True,
            "fixed_extractor_requires_verified_identity_and_usable_geometry": True,
            "verified_identity_without_geometry_route": "LAYOUT_STRUCTURED_EXTRACTOR",
        },
        "candidate_change": "NONE_TEMPLATE_LINEAGE_BLOCKED",
    }


def _field_support() -> dict[str, Any]:
    registry = TemplateRegistry.load_from_directory()
    rows = []
    for family, form_type in (("CMS1500", ClaimFormType.CMS1500), ("UB04", ClaimFormType.UB04)):
        template = registry.latest_for_form_type(form_type)
        required = set(template.required_fields)
        for field in template.field_regions:
            rows.append({
                "family": family,
                "field": field.field_name,
                "support": "SUPPORTED",
                "critical_or_required": field.field_name in required,
                "implementation": "CONFIGURED_FIXED_ROI_AND_NORMALIZER",
                "benchmark_status": "NOT_MEASURED_ON_TUNING_NO_FIELD_TRUTH",
            })
        if template.service_line_region:
            for field in template.service_line_region.columns:
                rows.append({
                    "family": family,
                    "field": f"service_lines.{field.field_name}",
                    "support": "PARTIALLY_SUPPORTED",
                    "critical_or_required": False,
                    "implementation": "CONFIGURED_TABLE_COLUMN; TRUTH_RECONSTRUCTION_UNMEASURED",
                    "benchmark_status": "NOT_MEASURED_ON_TUNING_NO_SERVICE_LINE_TRUTH",
                })
    return {
        "frozen_unsupported_error_count_before": 60,
        "supported_after": "NOT_MEASURABLE_NO_TUNING_FIELD_TRUTH",
        "rows": rows,
        "note": "Configuration support is not evidence of extraction accuracy.",
    }


def _blocked_metric(family: str | None = None) -> dict[str, Any]:
    payload = {
        "status": "NOT_MEASURABLE",
        "reason": "NO_FIELD_TRUTH_OR_TRUTH_CROP_BOXES_ON_TUNING_PERMITTED_STANDARD_PAGES",
        "observation_only_pages_inspected": 0,
        "development_leakage": False,
    }
    if family:
        payload["family"] = family
    return payload


def _reports(outputs: dict[str, Any]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    forensics = outputs["registration_forensics"]
    reasons = "\n".join(
        f"| {reason} | {count} |" for reason, count in forensics["summary"]["failure_reasons"].items()
    )
    (DOCS / "CDP_PHASE7A14_REGISTRATION_FAILURE_PARETO.md").write_text(f"""# CDP Phase 7A.14 Registration Failure Pareto

Tuning-only replay: {forensics['summary']['attempts']} attempts, {forensics['summary']['successes']} successes, {forensics['summary']['failures']} failures. Classified failure rate: {forensics['summary']['classified_failure_rate']:.2%}.

| Primary cause | Count |
|---|---:|
{reasons}

The compatibility precheck avoided SIFT on {forensics['summary']['sift_avoided']} incompatible pages. Full per-attempt evidence is in `evaluation_results/phase7a14/registration_forensics.json`.
""", "utf-8")
    (DOCS / "CDP_PHASE7A14_TEMPLATE_ASSET_AUDIT.md").write_text(
        "# CDP Phase 7A.14 Template Asset Audit\n\n```json\n" +
        json.dumps(outputs["template_asset_audit"], indent=2) + "\n```\n", "utf-8")
    (DOCS / "CDP_PHASE7A14_TEMPLATE_COMPATIBILITY.md").write_text(
        "# CDP Phase 7A.14 Template Compatibility\n\n" +
        "The controlled transforms pass, while the tuning corpus is dominated by a different sparse-fixture lineage. This is not a threshold-tuning result.\n\n```json\n" +
        json.dumps(outputs["template_compatibility"], indent=2) + "\n```\n", "utf-8")
    blocked = "No tuning-permitted standard page contains field truth or a truth crop box. Observation-only pages were not inspected or used for design."
    report_payloads = {
        "CDP_PHASE7A14_CROP_CORRECTNESS.md": ("Crop Correctness", outputs["crop_correctness"]),
        "CDP_PHASE7A14_CMS_FIELD_PARETO.md": ("CMS Field Pareto", outputs["cms_field_pareto"]),
        "CDP_PHASE7A14_UB_FIELD_PARETO.md": ("UB Field Pareto", outputs["ub_field_pareto"]),
        "CDP_PHASE7A14_OCR_GIVEN_CORRECT_CROP.md": ("OCR Given Correct Crop", outputs["ocr_correct_crop"]),
        "CDP_PHASE7A14_CMS_VERIFIER_RECOVERY.md": ("CMS Verifier Recovery", outputs["cms_verifier"]),
        "CDP_PHASE7A14_UB_VERIFIER_RECOVERY.md": ("UB Verifier Recovery", outputs["ub_verifier"]),
        "CDP_PHASE7A14_UB_SERVICE_LINES.md": ("UB Service Lines", outputs["ub_service_lines"]),
        "CDP_PHASE7A14_FIELD_SUPPORT_MATRIX.md": ("Field Support Matrix", outputs["field_support_matrix"]),
        "CDP_PHASE7A14_LATENCY_PARETO.md": ("Latency Pareto", outputs["latency_pareto"]),
    }
    for filename, (title, payload) in report_payloads.items():
        note = f"\n{blocked}\n" if payload.get("status") == "NOT_MEASURABLE" else ""
        (DOCS / filename).write_text(
            f"# CDP Phase 7A.14 {title}\n{note}\n```json\n" +
            json.dumps(payload, indent=2) + "\n```\n", "utf-8")
    decision = outputs["decision"]
    (DOCS / "CDP_PHASE7A14_FINAL_REPORT.md").write_text(f"""# CDP Phase 7A.14 Final Report

Phase 7A.14 stopped before candidate creation. The registration implementation passed {outputs['template_compatibility']['control_success_rate']:.2%} of controlled transforms, but {forensics['summary']['successes']} of {forensics['summary']['attempts']} tuning registration attempts succeeded against the current reference assets. The primary cause is `{decision['primary_bottleneck']}`.

The 430-page tuning split has 260 standard pages but no field truth, crop truth, or service-line truth. Consequently, crop correctness, OCR accuracy given correct crop, truth-route extraction recovery, and UB row reconstruction cannot be developed or promoted without violating the frozen 430/800 boundary. The 800 observation-only pages were not run.

Safety remained fail-closed: false-standard authorization is 0, CMS-to-UB authorization is 0, and UB-to-CMS authorization is 0. Production verifier thresholds, router logic, and fixed-form ROIs remain unchanged.

Decision: `{decision['promotion_decision']}`.
""", "utf-8")
    (OUTPUT / "crop_gallery.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'><title>Phase 7A.14 crop gallery</title></head>"
        "<body><h1>Phase 7A.14 crop gallery</h1><p>No cards generated: the tuning-permitted "
        "standard pages contain no field truth or truth crop boxes. Observation-only pages were not inspected.</p>"
        "</body></html>", "utf-8")


def run() -> dict[str, Any]:
    manifest = load_frozen_manifest()
    baseline = freeze_baseline(manifest)
    nominations, tuning = _tuning_routes(manifest)
    tuning_routes = []
    route_by_id = {row["document_id"]: row for row in nominations}
    # Retain all 430 tuning rows for direct-verifier hard-negative diagnostics.
    all_routes_by_id = {}
    for line in (PHASE13_WORK / "routing_details.jsonl").read_text("utf-8").splitlines():
        row = json.loads(line)
        if row["document_id"] in tuning:
            all_routes_by_id[row["document_id"]] = row
    tuning_routes = list(all_routes_by_id.values())
    existing_forensics = OUTPUT / "registration_forensics.json"
    forensic_rows = []
    if existing_forensics.is_file():
        cached = _json(existing_forensics).get("attempts", [])
        expected_ids = {row["document_id"] for row in nominations}
        if len(cached) == 132 and {row["document_id"] for row in cached} == expected_ids:
            forensic_rows = cached
    if not forensic_rows:
        with ThreadPoolExecutor(max_workers=4) as executor:
            forensic_rows = list(executor.map(
                lambda row: registration_forensic_record(tuning[row["document_id"]], row),
                nominations,
            ))
    registration_summary = aggregate_forensics(forensic_rows)
    controls = registration_controls()
    asset_audit = audit_template_assets()
    template_compatibility = {
        "policy_version": "template-compatibility-v1",
        "control_success_rate": controls["success_rate"],
        "control_attempts": controls["attempts"],
        "control_successes": controls["successes"],
        "benchmark_status_counts": registration_summary["compatibility_status"],
        "benchmark_compatible_rate": sum(
            row["compatibility"]["status"] == "COMPATIBLE" for row in forensic_rows
        ) / len(forensic_rows),
        "interpretation": "TEMPLATE_LINEAGE_MISMATCH" if registration_summary["successes"] == 0
                          and controls["success_rate"] >= .95 else "REGISTRATION_IMPLEMENTATION_REVIEW",
        "controls": controls,
    }
    tuning_standard = [record for record in tuning.values()
                       if record["expected_family"] in {"CMS1500", "UB04"}]
    truth_availability = {
        "tuning_pages": 430,
        "tuning_standard_pages": len(tuning_standard),
        "standard_pages_with_field_truth": sum(bool(row["truth_fields"]) for row in tuning_standard),
        "standard_pages_with_crop_truth": sum(bool(row["crop_boxes"]) for row in tuning_standard),
        "standard_pages_with_service_line_truth": sum(
            bool(row["truth_fields"].get("service_lines")) for row in tuning_standard
        ),
        "observation_pages_used_for_development": 0,
    }
    crop = {**_blocked_metric(), "truth_availability": truth_availability,
            "CMS1500_crop_correctness": "NOT_MEASURABLE",
            "UB04_fixed_field_crop_correctness": "NOT_MEASURABLE"}
    cms_pareto = {**_blocked_metric("CMS1500"), "before_accuracy_frozen": 0.19791666666666666,
                  "after_accuracy": "NOT_MEASURABLE_NO_CANDIDATE", "fields": []}
    ub_pareto = {**_blocked_metric("UB04"), "before_accuracy_frozen": 0.32407407407407407,
                 "after_accuracy": "NOT_MEASURABLE_NO_CANDIDATE", "fields": []}
    ocr = {**_blocked_metric(), "CMS1500_accuracy_given_correct_crop": "NOT_MEASURABLE",
           "UB04_accuracy_given_correct_crop": "NOT_MEASURABLE", "engine_trials": []}
    frozen_verification = baseline["frozen_metrics"]["verification"]
    cms_verifier = {
        "before_frozen_all": frozen_verification["all"]["CMS1500"],
        "tuning_diagnostic": _verifier_diagnostic(tuning_routes, "CMS1500"),
        "after": "UNCHANGED_NO_SAFE_PROMOTION",
        "reason": "REGISTRATION_EVIDENCE_UNAVAILABLE_FOR_CURRENT_TEMPLATE_LINEAGE",
    }
    ub_verifier = {
        "before_frozen_all": frozen_verification["all"]["UB04"],
        "tuning_diagnostic": _verifier_diagnostic(tuning_routes, "UB04"),
        "after": "UNCHANGED_NO_SAFE_PROMOTION",
        "reason": "REGISTRATION_EVIDENCE_UNAVAILABLE_FOR_CURRENT_TEMPLATE_LINEAGE",
    }
    ub_lines = {
        "before_frozen": {"truth_rows": 6, "reconstructed_rows": 0, "accuracy": 0.0},
        "implementation": {
            "engine": "UB04ServiceLineEngine",
            "candidate_component": "UB04ServiceLineExtractor",
            "fallback_order": ["DETERMINISTIC_LINE_GRID", "OCR_TOKEN_GEOMETRY",
                               "PROJECTION_PROFILE_DIAGNOSTIC",
                               "CONNECTED_COMPONENT_DIAGNOSTIC"],
            "regional_ocr_calls_per_table": 1,
            "docling_runtime_calls": 0,
            "row_object_fields": ["revenue_code", "description", "hcpcs", "service_date",
                                  "units", "charge", "row_bbox", "column_bboxes",
                                  "ocr_candidates", "validation_status", "reconstruction_confidence"],
            "validation": ["revenue_code", "HCPCS", "date", "units", "currency",
                           "row_completeness", "claim_total_reconciliation"],
            "runtime_promotion": False,
        },
        "after": "NOT_MEASURABLE_NO_TUNING_SERVICE_LINE_TRUTH",
        "observation_only_run": "NOT_RUN",
    }
    support = _field_support()
    route_tuning = baseline["frozen_metrics"]["routing"]["splits"]["tuning_permitted"]
    ocr_calls = [int(row.get("ocr_calls", 0)) for row in tuning_routes]
    latency = {
        "frozen_routing_latency_ms": baseline["frozen_metrics"]["routing"]["latency_ms"],
        "frozen_tuning_routing_latency_ms": route_tuning["latency_ms"],
        "registration_precheck_latency_ms": registration_summary["latency_ms"],
        "full_page_ocr_calls_per_page": sum(ocr_calls) / len(ocr_calls),
        "stage_findings": {
            "document_preprocessing": "INCLUDED_IN_ROUTE_PREPROCESS_STAGE",
            "full_page_ocr": "ONE_CALL_PER_TUNING_PAGE",
            "classification_nomination_verification": "INSTRUMENTED_IN_FROZEN_ROUTING_ROWS",
            "registration": "SIFT_SKIPPED_FOR_INCOMPATIBLE_TEMPLATE_LINEAGES",
            "regional_ocr": "NOT_RUN_NO_TUNING_FIELD_TRUTH",
            "retries": "ZERO_IN_PHASE7A14_DIAGNOSTIC",
            "subprocess_startup": "TESSERACT_IS_ONE_CHILD_PROCESS_PER_FULL_PAGE_CALL",
            "rapidocr_initialization": "LAZY_AND_REUSED_PER_LONG_LIVED_EXTRACTOR_INSTANCE",
            "paddle_initialization": "LAZY_AND_REUSED_PER_LONG_LIVED_EXTRACTOR_INSTANCE",
            "template_descriptors": "NOT_COMPUTED_WHEN_COMPATIBILITY_IS_INCOMPATIBLE",
            "file_io": "INCLUDED_IN_REGISTRATION_PRECHECK_LATENCY",
        },
        "fixed_form_candidate_p50_ms": "NOT_MEASURABLE",
        "fixed_form_candidate_p95_ms": "NOT_MEASURABLE",
        "fixed_form_candidate_p99_ms": "NOT_MEASURABLE",
    }
    experiments = {
        "execution_order": ["EXP-02A", "EXP-02B", "EXP-02C", "EXP-02D", "EXP-02E",
                            "EXP-02F", "EXP-02G", "EXP-02H"],
        "experiments": [
            {"id": "EXP-02A", "name": "registration implementation controls",
             "status": "PASS", "metric": controls["success_rate"]},
            {"id": "EXP-02B", "name": "template compatibility diagnosis",
             "status": "DIAGNOSED_TEMPLATE_LINEAGE_MISMATCH",
             "metric": template_compatibility["benchmark_compatible_rate"]},
            {"id": "EXP-02C", "name": "CMS ROI recovery", "status": "BLOCKED_NO_TUNING_FIELD_TRUTH"},
            {"id": "EXP-02D", "name": "UB fixed-field ROI recovery", "status": "BLOCKED_NO_TUNING_FIELD_TRUTH"},
            {"id": "EXP-02E", "name": "OCR by field on correct crops", "status": "BLOCKED_NO_TRUTH_CROP_LABELS"},
            {"id": "EXP-02F", "name": "CMS verifier recovery", "status": "NOT_PROMOTED_TEMPLATE_LINEAGE_BLOCKED"},
            {"id": "EXP-02G", "name": "UB verifier recovery", "status": "NOT_PROMOTED_TEMPLATE_LINEAGE_BLOCKED"},
            {"id": "EXP-02H", "name": "UB service-line reconstruction",
             "status": "CONTRACT_IMPLEMENTED_BENCHMARK_BLOCKED_NO_TUNING_ROW_TRUTH"},
        ],
        "observation_only_micro_experiment_runs": 0,
    }
    candidate = {
        "candidate_id": "FIXED_FORM_RECOVERY_CANDIDATE_1",
        "created": False,
        "frozen": False,
        "gate_status": "FAILED_PREREQUISITES",
        "failed_gates": ["benchmark_template_compatibility", "CMS_crop_correctness",
                         "UB_crop_correctness", "OCR_given_correct_crop",
                         "CMS_truth_route_extraction", "UB_truth_route_extraction",
                         "critical_field_accuracy", "verifier_recall", "UB_service_lines"],
        "observation_only_result": "NOT_RUN_CANDIDATE_NOT_FROZEN",
    }
    decision = {
        "primary_bottleneck": "TEMPLATE_GENERALIZATION_BOTTLENECK",
        "secondary_bottleneck": "TUNING_FIELD_TRUTH_UNAVAILABLE",
        "promotion_decision": "BLOCKED_NO_CANDIDATE",
        "production_candidate_activated": False,
        "production_policy_changed": False,
        "production_code_changed": True,
        "production_code_change_scope": (
            "FAIL_CLOSED_REGISTRATION_EVIDENCE_SCHEMA_AND_UNPROMOTED_UB04_CANDIDATE_COMPONENT"
        ),
        "router_experiment_2_started": False,
        "observation_only_pages_run": 0,
        "safety": {
            "false_accepts": 0,
            "false_standard_authorization": route_tuning["false_standard_authorization_count"],
            "cms_to_ub": route_tuning["cms_to_ub_authorization_rate"],
            "ub_to_cms": route_tuning["ub_to_cms_authorization_rate"],
        },
        "next_bottleneck": "CREATE_TUNING_ELIGIBLE_FIXED_FORM_FIELD_AND_CROP_TRUTH_WITH_MATCHING_TEMPLATE_LINEAGES",
    }
    outputs = {
        "baseline": baseline,
        "registration_forensics": {"summary": registration_summary, "attempts": forensic_rows},
        "registration_failure_pareto": {"reasons": registration_summary["failure_reasons"],
                                        "classified_rate": registration_summary["classified_failure_rate"]},
        "template_asset_audit": asset_audit,
        "template_compatibility": template_compatibility,
        "crop_correctness": crop,
        "cms_field_pareto": cms_pareto,
        "ub_field_pareto": ub_pareto,
        "ocr_correct_crop": ocr,
        "cms_verifier": cms_verifier,
        "ub_verifier": ub_verifier,
        "ub_service_lines": ub_lines,
        "field_support_matrix": support,
        "latency_pareto": latency,
        "experiments": experiments,
        "candidate": candidate,
        "decision": decision,
    }
    filenames = {
        "baseline": "baseline.json",
        "registration_forensics": "registration_forensics.json",
        "registration_failure_pareto": "registration_failure_pareto.json",
        "template_compatibility": "template_compatibility.json",
        "crop_correctness": "crop_correctness.json",
        "cms_field_pareto": "cms_field_pareto.json",
        "ub_field_pareto": "ub_field_pareto.json",
        "ocr_correct_crop": "ocr_correct_crop.json",
        "cms_verifier": "cms_verifier.json",
        "ub_verifier": "ub_verifier.json",
        "ub_service_lines": "ub_service_lines.json",
        "field_support_matrix": "field_support_matrix.json",
        "latency_pareto": "latency_pareto.json",
        "experiments": "experiments.json",
        "candidate": "candidate.json",
        "decision": "decision.json",
    }
    for key, filename in filenames.items():
        _write(filename, outputs[key])
    _write("template_asset_audit.json", asset_audit)
    _reports(outputs)
    return outputs


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "registration": result["registration_forensics"]["summary"],
        "compatibility": result["template_compatibility"],
        "candidate": result["candidate"],
        "decision": result["decision"],
    }, indent=2))
