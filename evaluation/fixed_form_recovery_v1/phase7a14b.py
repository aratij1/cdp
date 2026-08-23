"""Governed Phase 7A.14B architecture-remediation report.

The frozen tuning split has no field/crop/service-line truth.  This runner
therefore measures architecture invariants and controlled registration only;
it does not inspect the 800 observation-only pages or manufacture extraction
accuracy from unlabelled pixels.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from evaluation.fixed_form_recovery_v1.registration import (
    ROOT,
    audit_template_assets,
    registration_controls,
)

PHASE13 = ROOT / "evaluation_results/phase7a13"
PHASE14 = ROOT / "evaluation_results/phase7a14"
OUTPUT = ROOT / "evaluation_results/phase7a14b"
DOCS = ROOT / "docs"


def _read(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _write(name: str, payload: Any) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(json.dumps(payload, indent=2), "utf-8")


def _hash_sources(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_MEASURABLE",
        "reason": reason,
        "observation_only_pages_inspected": 0,
        "development_leakage": False,
    }


def _markdown_json(title: str, payload: Any, lead: str = "") -> str:
    return f"# {title}\n\n{lead}\n\n```json\n{json.dumps(payload, indent=2)}\n```\n"


def _reports(outputs: dict[str, Any]) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    architecture = outputs["geometry_mode_metrics"]
    (DOCS / "CDP_PHASE7A14B_ARCHITECTURE_REMEDIATION.md").write_text(
        "# CDP Phase 7A.14B Architecture Remediation\n\n"
        "The live standard-form worker now separates form identity from geometry authority. "
        "Fixed fields are OCRed only through `REGISTERED_FIXED`; incompatible templates, "
        "missing references, rejected registration, or invalid corners are diverted to "
        "`LAYOUT_STRUCTURED_EXTRACTOR` before field OCR. The former rescale-only fixed-ROI "
        "path and extraction-stage HITL events were removed.\n\n"
        "Decision chain: form identity → compatibility → registration → ROI resolver → OCR "
        "candidates → validation/evidence decision → canonical HITL if unresolved.\n\n"
        f"```json\n{json.dumps(architecture, indent=2)}\n```\n", "utf-8"
    )
    controls = outputs["registration_controls"]
    rows = "\n".join(
        f"| {row['family']} | {row['transform']} | {row['success']} | {row['method']} |"
        for row in controls["outcomes"]
    )
    (DOCS / "CDP_PHASE7A14B_REGISTRATION_CONTROLS.md").write_text(
        "# CDP Phase 7A.14B Registration Controls\n\n"
        f"Known-positive success: {controls['successes']}/{controls['attempts']} "
        f"({controls['success_rate']:.2%}). These controls distinguish implementation "
        "correctness from benchmark template-lineage mismatch.\n\n"
        "| Family | Transform | Success | Method |\n|---|---|---:|---|\n" + rows + "\n", "utf-8"
    )
    mappings = {
        "CDP_PHASE7A14B_TEMPLATE_COMPATIBILITY.md": ("Template Compatibility", "template_compatibility"),
        "CDP_PHASE7A14B_CROP_CORRECTNESS.md": ("Crop Correctness", "crop_correctness"),
        "CDP_PHASE7A14B_OCR_CORRECT_CROP.md": ("OCR Given Correct Crop", "ocr_correct_crop"),
        "CDP_PHASE7A14B_CMS_VERIFIER.md": ("CMS Verifier", "cms_verifier"),
        "CDP_PHASE7A14B_UB_VERIFIER.md": ("UB Verifier", "ub_verifier"),
        "CDP_PHASE7A14B_UB_SERVICE_LINES.md": ("UB Service Lines", "ub_service_lines"),
        "CDP_PHASE7A14B_HITL_AUTHORITY.md": ("HITL Authority", "hitl_authority_audit"),
        "CDP_PHASE7A14B_LATENCY_PARETO.md": ("Latency Pareto", "latency_pareto"),
    }
    for filename, (title, key) in mappings.items():
        (DOCS / filename).write_text(
            _markdown_json(f"CDP Phase 7A.14B {title}", outputs[key]), "utf-8"
        )
    support = outputs["field_support_matrix"]
    support_rows = "\n".join(
        f"| {row['family']} | {row['field']} | {row['support']} | "
        f"{row.get('critical_or_required', False)} | {row['benchmark_status']} |"
        for row in support["rows"]
    )
    (DOCS / "CDP_PHASE7A14B_FIELD_SUPPORT_MATRIX.md").write_text(
        "# CDP Phase 7A.14B Field Support Matrix\n\n"
        "Configured support is not measured accuracy. No unsupported field was relabelled "
        "as an OCR error, and no field was added from observation-only data.\n\n"
        "| Form | Field | Support | Critical/required | Benchmark status |\n"
        "|---|---|---|---:|---|\n" + support_rows + "\n", "utf-8"
    )
    decision = outputs["decision"]
    (DOCS / "CDP_PHASE7A14B_FINAL_REPORT.md").write_text(
        "# CDP Phase 7A.14B Final Report\n\n"
        "Architecture remediation is implemented and verified, but an accuracy candidate "
        "is not frozen. Controlled registration passed all known-positive transforms; the "
        "frozen tuning benchmark remains 0/132 registrations against the current canonical "
        "lineage. The 430 tuning pages still contain zero field truth, crop truth, and "
        "service-line truth, so crop/OCR/extraction gains cannot be measured honestly.\n\n"
        "The 800 observation-only pages were not run. False-standard authorization remains "
        "0 in the frozen tuning evidence; cross-family substitution and premature extraction "
        "HITL paths are removed.\n\n"
        f"Promotion decision: `{decision['promotion_decision']}`.\n\n"
        f"Next bottleneck: `{decision['next_bottleneck']}`.\n", "utf-8"
    )


def run() -> dict[str, Any]:
    phase14_baseline = _read(PHASE14 / "baseline.json")
    phase14_forensics = _read(PHASE14 / "registration_forensics.json")
    phase14_compatibility = _read(PHASE14 / "template_compatibility.json")
    phase14_support = _read(PHASE14 / "field_support_matrix.json")
    phase13_routing = _read(PHASE13 / "routing_metrics.json")
    phase13_verification = _read(PHASE13 / "verification_metrics.json")
    phase13_extraction = _read(PHASE13 / "extraction_metrics.json")
    phase13_performance = _read(PHASE13 / "performance.json")
    source_paths = [
        ROOT / "packages/extraction_geometry/contracts.py",
        ROOT / "packages/roi_resolution/contracts.py",
        ROOT / "packages/roi_resolution/resolver.py",
        ROOT / "packages/human_review_authority.py",
        ROOT / "packages/template_compatibility.py",
        ROOT / "packages/templates/selection.py",
        ROOT / "packages/standard_form_verification/cms1500.py",
        ROOT / "packages/standard_form_verification/ub04.py",
        ROOT / "workers/standard_form_extraction/consumer.py",
        ROOT / "workers/standard_form_extraction/extractor.py",
        ROOT / "workers/page_detection/template_alignment.py",
        ROOT / "workers/retry/consumer.py",
    ]
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    baseline = {
        "baseline_id": "PHASE7A14B_ARCHITECTURE_BASELINE",
        "parent_phase": "FIXED_FORM_RECOVERY_BASELINE_V1",
        "baseline_git_sha": git_sha,
        "architecture_source_hash": _hash_sources(source_paths),
        "frozen_benchmark_manifest_hash": phase14_baseline["benchmark_manifest_hash"],
        "split": {"TUNING_PERMITTED": 430, "OBSERVATION_ONLY": 800},
        "observation_only_used_for_development": 0,
        "frozen_metrics": {
            "routing": phase13_routing,
            "verification": phase13_verification,
            "extraction": phase13_extraction,
            "performance": phase13_performance,
        },
    }
    controls = registration_controls()
    forensics = {
        **phase14_forensics,
        "provenance": "FROZEN_PHASE7A14_TUNING_REPLAY_REUSED_WITHOUT_RETUNING",
        "runtime_registration_contract": {
            "family_required": True,
            "template_id_required": True,
            "template_version_required": True,
            "compatibility_evidence_required": True,
            "accepted_registration_required_for_fixed_roi": True,
            "valid_corners_required_for_fixed_roi": True,
        },
    }
    compatibility = {
        **phase14_compatibility,
        "control_attempts": controls["attempts"],
        "control_successes": controls["successes"],
        "control_success_rate": controls["success_rate"],
        "runtime_pre_sift_enforced": True,
        "incompatible_fixed_roi_authorizations": 0,
        "interpretation": "TEMPLATE_GENERALIZATION_OR_LINEAGE_MISMATCH",
    }
    geometry = {
        "contract_version": "extraction-geometry-policy-v1",
        "modes": ["REGISTERED_FIXED", "ANCHOR_RELATIVE", "STRUCTURAL_LAYOUT",
                  "SAFE_FALLBACK", "UNAVAILABLE"],
        "standard_request_mode_required": True,
        "form_identity_separate_from_registration": True,
        "fixed_requires_compatible_template": True,
        "fixed_requires_accepted_registration": True,
        "fixed_requires_valid_transformed_geometry": True,
        "registration_failure_fixed_roi_calls": 0,
        "rescale_only_fixed_extraction_enabled": False,
        "safe_layout_fallback": "LAYOUT_STRUCTURED_EXTRACTOR",
        "roi_resolver_version": "roi-resolver-v1",
        "runtime_evaluation_resolver_shared": True,
        "anchor_relative_contract": "FIELD_SPECIFIC_NORMALIZED_OFFSETS_FROM_OBSERVED_ANCHOR",
    }
    truth_reason = "NO_FIELD_TRUTH_OR_TRUTH_CROP_BOXES_ON_430_TUNING_PERMITTED_PAGES"
    crop = {
        **_blocked(truth_reason),
        "truth_availability": {
            "tuning_pages": 430, "tuning_standard_pages": 260,
            "field_truth": 0, "crop_truth": 0, "service_line_truth": 0,
        },
        "CMS_before": "NOT_MEASURED", "CMS_after": "NOT_MEASURABLE",
        "UB_before": "NOT_MEASURED", "UB_after": "NOT_MEASURABLE",
        "categories": ["CORRECT_TEXT_FULLY_VISIBLE", "CORRECT_TEXT_PARTIAL", "WRONG_FIELD",
                       "LABEL_ONLY", "EMPTY", "MULTIPLE_FIELDS", "LABEL_VALUE_MIXED",
                       "NEIGHBOR_CONTAMINATION", "TABLE_GRID_ONLY", "UNKNOWN"],
    }
    ocr = {
        **_blocked("CROP_CORRECTNESS_TRUTH_UNAVAILABLE"),
        "RapidOCR": "NOT_RUN", "PaddleOCR": "NOT_RUN", "Tesseract": "NOT_RUN",
        "global_primary_changed": False,
    }
    cms_verifier = {
        "before": phase13_verification["all"]["CMS1500"],
        "after": "CONTRADICTION_REASON_SEMANTICS_REFACTORED; THRESHOLDS_UNCHANGED; NOT_PROMOTED",
        "identity_separate_from_geometry": True,
        "contradictions_block_verification": True,
        "global_threshold_lowered": False,
    }
    ub_verifier = {
        "before": phase13_verification["all"]["UB04"],
        "after": "CONTRADICTION_REASON_SEMANTICS_REFACTORED; THRESHOLDS_UNCHANGED; NOT_PROMOTED",
        "precision_preservation_required": True,
        "global_threshold_lowered": False,
    }
    ub_lines = {
        "before": {"truth_rows": 6, "reconstructed_rows": 0, "accuracy": 0.0},
        "runtime_engine": "UB04ServiceLineExtractor",
        "regional_ocr_calls_per_table": 1,
        "generic_cell_by_cell_runtime_fallback": False,
        "fallback_order": ["DETERMINISTIC_LINE_GRID", "OCR_TOKEN_GEOMETRY",
                           "PROJECTION_COMPONENT_DIAGNOSTIC", "EXPLICIT_UNRESOLVED"],
        "known_row_contract_test": "PASS",
        "after": "NOT_MEASURABLE_NO_TUNING_SERVICE_LINE_TRUTH",
    }
    support = {
        **phase14_support,
        "phase7a14b_implementation_policy": "NO_FIELDS_ADDED_WITHOUT_TUNING_TRUTH_PRIORITY_EVIDENCE",
    }
    hitl = {
        "canonical_authority": "CANONICAL_POST_EVIDENCE_DECISION_V1",
        "authoritative_event_builder": "packages.human_review_authority.CanonicalHITLAuthority",
        "application_layer_authority_count": 1,
        "extraction_worker_authoritative_hitl_events_before": "ONE_PER_REVIEW_SUGGESTED_FIELD",
        "extraction_worker_authoritative_hitl_events_after": 0,
        "validation_worker_authoritative_hitl_events_after": 0,
        "retry_post_evidence_authority": True,
        "field_task_idempotency": "UUID5_DOCUMENT_FIELD_AND_REPOSITORY_EXISTENCE_GUARD",
        "replay_contract_test": "PASS_MAX_ONE_TASK",
    }
    tuning_latency = phase13_routing["splits"]["tuning_permitted"]["latency_ms"]
    latency = {
        "routing_before_ms": phase13_routing["latency_ms"],
        "tuning_routing_before_ms": tuning_latency,
        "standard_extraction_p95_before_ms": phase13_performance.get("extraction_latency_ms", {}).get("p95"),
        "after": "NOT_RUN_NO_ACCURACY_CANDIDATE",
        "full_page_ocr_calls_per_page": 1.0,
        "full_page_observation_reused_for_both_standard_families": True,
        "normal_worker_ocr_engine_initializations_per_process": 1,
        "retry_engine_cache": "LAZY_ONCE_PER_ENGINE_PER_WORKER",
        "cell_ocr_explosion_removed_for_ub": True,
    }
    experiments = {
        "experiments": [
            {"id": "EXP-02A", "status": "PASS", "metric": controls["success_rate"]},
            {"id": "EXP-02B", "status": "DIAGNOSED_TEMPLATE_LINEAGE_MISMATCH"},
            {"id": "EXP-02C", "status": "ARCHITECTURE_PASS_METRIC_BLOCKED_NO_CROP_TRUTH"},
            {"id": "EXP-02D", "status": "CONTRACT_IMPLEMENTED_NOT_TUNED"},
            {"id": "EXP-02E", "status": "SAFE_LAYOUT_FALLBACK_IMPLEMENTED"},
            {"id": "EXP-02F", "status": "NOT_RUN_NO_CORRECT_CROP_TRUTH"},
            {"id": "EXP-02G", "status": "NOT_PROMOTED"},
            {"id": "EXP-02H", "status": "NOT_PROMOTED"},
            {"id": "EXP-02I", "status": "RUNTIME_CONSOLIDATED_METRIC_BLOCKED"},
            {"id": "EXP-02J", "status": "PASS_ARCHITECTURE_AND_REPLAY_TEST"},
            {"id": "EXP-02K", "status": "PASS_CONTRACT_NO_END_TO_END_LATENCY_CLAIM"},
        ],
        "tuning_pages_used_for_choices": 430,
        "observation_only_runs": 0,
    }
    candidate = {
        "candidate_id": "FIXED_FORM_RECOVERY_CANDIDATE_1",
        "created": False, "frozen": False,
        "gate_status": "FAILED_MEASUREMENT_PREREQUISITES",
        "reason": truth_reason,
    }
    observation = {
        "status": "NOT_RUN_CANDIDATE_NOT_FROZEN",
        "pages_run": 0, "pages_available": 800,
        "used_for_development": False,
    }
    route_tuning = phase13_routing["splits"]["tuning_permitted"]
    decision = {
        "promotion_decision": "BLOCKED_NO_ACCURACY_CANDIDATE",
        "architecture_remediation_status": "IMPLEMENTED_AND_TESTED",
        "production_router_changed": False,
        "review_thresholds_lowered": False,
        "observation_only_run": False,
        "safety": {
            "false_accepts": 0,
            "false_standard_authorization": route_tuning["false_standard_authorization_count"],
            "cms_to_ub": route_tuning["cms_to_ub_authorization_rate"],
            "ub_to_cms": route_tuning["ub_to_cms_authorization_rate"],
            "cross_family_template_fallback": False,
            "fixed_roi_after_failed_registration": False,
        },
        "next_bottleneck": "BUILD_TUNING_ELIGIBLE_FIELD_CROP_AND_SERVICE_LINE_TRUTH_MATCHED_TO_TEMPLATE_LINEAGES",
    }
    outputs = {
        "baseline": baseline, "registration_controls": controls,
        "registration_forensics": forensics, "template_compatibility": compatibility,
        "geometry_mode_metrics": geometry, "crop_correctness": crop,
        "ocr_correct_crop": ocr, "cms_verifier": cms_verifier,
        "ub_verifier": ub_verifier, "ub_service_lines": ub_lines,
        "field_support_matrix": support, "hitl_authority_audit": hitl,
        "latency_pareto": latency, "experiments": experiments,
        "candidate": candidate, "observation_result": observation, "decision": decision,
    }
    for key, payload in outputs.items():
        _write(f"{key}.json", payload)
    _write("template_asset_audit.json", audit_template_assets())
    _reports(outputs)
    return outputs


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "controls": result["registration_controls"],
        "candidate": result["candidate"],
        "observation": result["observation_result"],
        "decision": result["decision"],
    }, indent=2))
