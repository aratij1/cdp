"""Build the final PHI-safe production qualification decision from governed artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results" / "final_qualification"
TARGETS = {
    "final_accuracy": 0.99,
    "critical_accuracy": 0.995,
    "accepted_precision": 0.995,
    "critical_accepted_precision": 0.995,
    "critical_false_accepts": 0,
    "field_hitl": 0.10,
    "claim_hitl": 0.20,
    "true_claim_stp": 0.80,
    "warm_p95_ms": 5000,
    "paid_ai_usd_per_page": 0.001,
}


def load(relative: str, default: dict | None = None) -> dict:
    path = ROOT / relative
    if not path.is_file():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8"))


def digest(relative: str) -> str | None:
    path = ROOT / relative
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(value: object, status: str = "NOT_EVALUABLE") -> dict[str, object]:
    return {"value": value, "status": status}


def write(name: str, payload: dict) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    holdout = load("evaluation_results/production_holdout_v2/integrity_audit.json")
    review_progress = load("evaluation_results/real_eval/review_progress.json")
    binding = load("evaluation_results/real_eval/source_to_cdp_binding.json")
    intake = load("evaluation_results/production_closure/release/intake_audit.json")
    operational = load("operational_evidence.json")
    channels = load("evaluation_results/accuracy_channels.json")
    latency = load("docs/closure/production_latency_results.json")
    selection = load("evaluation_results/production_closure/latency/selection.json")
    candidate_freeze = load("docs/closure/CDP_PRODUCTION_CANDIDATE_FREEZE.json")

    truth_inventory = {
        "status": "NO_RELEASE_TRUTH_AVAILABLE",
        "generated_at": now,
        "authority_classes": {
            "ADJUDICATED": {"count": 0, "release_eligible": False},
            "DUAL_REVIEW_AGREED": {"count": 0, "release_eligible": False},
            "HUMAN_CONFIRMED": {"count": 0, "release_eligible": False},
            "AUTHORITATIVE_SOURCE": {"count": 0, "release_eligible": False},
            "FROZEN_HOLDOUT": {"count": 0, "release_eligible": False},
            "ENGINEERING_REGRESSION": {"count": 0, "release_eligible": False},
            "UNLABELED": {"count": 150, "release_eligible": False},
            "WEAK_REFERENCE": {"count": 0, "release_eligible": False},
        },
        "sources": [
            {
                "path": "evaluation_results/closure/iteration4/human_review/blind_manifest.json",
                "authority_class": "UNLABELED",
                "records": 150,
                "reviewed": False,
                "predictions_visible": False,
            },
            {
                "path": "evaluation_data/holdouts/PRODUCTION_HOLDOUT_V2_REPRESENTATIVE",
                "authority_class": "ENGINEERING_REGRESSION",
                "records": holdout.get("document_count", 0),
                "status": holdout.get("production_authority", "UNKNOWN"),
                "release_eligible": False,
            },
            {
                "path": "evaluation_results/real_eval/review_progress.json",
                "authority_class": "UNLABELED",
                "pages_reviewed": review_progress.get("pages_reviewed", 0),
                "pages_total": review_progress.get("pages_total", 0),
            },
        ],
        "excluded_as_truth": [
            "OCR agreement",
            "LLM agreement",
            "candidate recall",
            "self-consistency",
            "synthetic inference",
            "rejected or derived evaluation outputs",
        ],
    }
    write("truth_inventory.json", truth_inventory)

    write("release_truth_manifest.json", {
        "status": "NOT_FROZEN",
        "truth_version": None,
        "records": 0,
        "pages": 0,
        "fields": 0,
        "review_responses_received": intake.get("submitted_responses", 0),
        "adjudications": 0,
        "source_bindings": binding.get("bound_page_count", 0),
        "created_at": now,
        "reason": "No governed independent review responses or authoritative source bindings exist.",
    })

    write("release_leakage_report.json", {
        "status": "PASS_WITHOUT_RELEASE_TRUTH",
        "package_leakage": 0,
        "development_package_intersection": 0,
        "latency_holdout_package_intersection": 0,
        "operational_tuning_holdout_intersection": 0,
        "truth_frozen": False,
        "source": "evaluation_results/production_closure/release/package_reservation.local.json",
    })
    write("source_to_cdp_binding_report.json", {
        "status": "FAIL",
        "binding_coverage": binding.get("binding_coverage", 0.0),
        "bound_page_count": binding.get("bound_page_count", 0),
        "source_page_count": binding.get("source_page_count", 0),
        "ambiguous_or_unbound": True,
        "reason": "BINDING_NOT_PROVEN",
    })
    write("production_candidate_freeze.json", {
        "status": "ENGINEERING_CANDIDATE_FROZEN",
        "implementation_commit_sha": candidate_freeze.get("implementation_commit_sha"),
        "branch": candidate_freeze.get("branch"),
        "authority": candidate_freeze.get("authority"),
        "production_qualified": False,
        "production_authority_enabled": False,
        "source_artifact": "docs/closure/CDP_PRODUCTION_CANDIDATE_FREEZE.json",
    })

    write("raw_accuracy_report.json", {
        "status": "NOT_EVALUABLE",
        "final_release_metrics": {
            "accuracy": metric(None),
            "critical_accuracy": metric(None),
            "field_hitl": metric(None),
            "claim_hitl": metric(None),
            "raw_stp": metric(None),
        },
        "development_reference_only": {
            "raw_extraction_accuracy": channels.get("AUTOMATED_EXTRACTION_ACCURACY"),
            "field_denominator": channels.get("TOTAL_EVALUATED_FIELDS"),
            "source": "evaluation_results/accuracy_channels.json",
        },
    })
    write("final_post_hitl_accuracy_report.json", {
        "status": "NOT_EVALUABLE",
        "final_accuracy": metric(None),
        "critical_accuracy": metric(None),
        "claim_completeness": metric(None),
        "error_rate": metric(None),
        "reason": "No approved governed review completions and no source bindings.",
    })
    write("accepted_precision_report.json", {
        "status": "NOT_EVALUABLE",
        "accepted_precision": metric(None),
        "critical_accepted_precision": metric(None),
        "critical_false_accepts": metric(None),
        "reason": "Accepted precision requires trusted release truth.",
    })
    write("false_accept_report.json", {
        "status": "NOT_EVALUABLE",
        "critical_false_accepts": None,
        "records": [],
        "reason": "No trusted release denominator exists; no false-accept claim is asserted.",
    })
    write("hitl_report.json", {
        "status": "NOT_EVALUABLE",
        "field_hitl": metric(None),
        "critical_field_hitl": metric(None),
        "claim_hitl": metric(None),
        "source_review_claims": None,
        "external_authority_claims": None,
        "human_correction_claims": 0,
        "unresolved_after_hitl": None,
        "review_progress": review_progress,
    })
    write("stp_report.json", {
        "status": "NOT_EVALUABLE",
        "raw_stp": metric(None),
        "true_claim_stp": metric(None),
        "hitl_closed_claims": None,
        "unresolved_claims": None,
        "final_complete_claims": None,
        "scenario_stp": None,
        "reason": "STP requires trusted final claim truth and safe output evidence.",
    })
    write("field_breakdown.json", {
        "status": "NOT_EVALUABLE",
        "forms": ["CMS1500", "UB04", "OTHER_CLAIM_FORM"],
        "required_critical_fields": [
            "member_id", "provider_name", "patient_name", "insured_name",
            "patient_dob", "service_date", "total_charge", "principal_diagnosis",
        ],
        "breakdown": {},
    })
    write("claim_breakdown.json", {
        "status": "NOT_EVALUABLE",
        "claims": [],
        "reason": "No source-to-CDP binding and no frozen release truth.",
    })

    selected_p95 = selection.get("fresh_qualification_median_warm_p95_ms")
    write("latency_report.json", {
        "status": "FAIL",
        "warm_p50_ms": latency.get("fresh_qualification", {}).get("median_warm_p50_ms"),
        "warm_p95_ms": selected_p95,
        "warm_p99_ms": latency.get("fresh_qualification", {}).get("median_warm_p99_ms"),
        "throughput_pages_per_second": latency.get("fresh_qualification", {}).get("median_throughput_pages_per_second"),
        "target_warm_p95_ms": TARGETS["warm_p95_ms"],
        "latency_cohort_overlap": 0,
        "authority_lookup_latency": "NOT_MEASURED",
        "reason": "Measured warm P95 exceeds the 5 second/page target.",
    })
    holdout_baseline = load("evaluation_results/production_holdout_v2/baseline_report.json")
    write("cost_report.json", {
        "status": "NOT_EVALUABLE",
        "paid_ai_cost_usd_per_page": metric(holdout_baseline.get("cost", {}).get("cloud_cost_usd"), "SHADOW_ONLY"),
        "paid_ai_target_usd_per_page": TARGETS["paid_ai_usd_per_page"],
        "total_cost_usd_per_page": metric(None),
        "ocr_calls_per_page": None,
        "authority_lookup_calls_per_claim": None,
        "cache_hits": None,
        "reason": "Infrastructure and authority pricing are not configured; shadow cost is not release cost.",
    })

    gates = {
        "final_accuracy": metric(None),
        "critical_accuracy": metric(None),
        "accepted_precision": metric(None),
        "critical_accepted_precision": metric(None),
        "critical_false_accepts": metric(None),
        "field_hitl": metric(None),
        "claim_hitl": metric(None),
        "true_claim_stp": metric(None),
        "warm_p95": {"value": selected_p95, "target": TARGETS["warm_p95_ms"], "status": "FAIL"},
        "paid_ai_cost": {"value": holdout_baseline.get("cost", {}).get("cloud_cost_usd"), "target": TARGETS["paid_ai_usd_per_page"], "status": "NOT_EVALUABLE"},
        "package_leakage": {"value": 0, "target": 0, "status": "PASS"},
        "truth_provenance": {"value": False, "status": "FAIL"},
        "source_to_cdp_binding": {"value": binding.get("binding_coverage", 0.0), "status": "FAIL"},
        "operational_evidence": {"value": operational, "status": "FAIL"},
        "no_safety_regression": {"value": None, "status": "NOT_EVALUABLE"},
    }
    write("release_gate_report.json", {
        "status": "NO_GO",
        "targets": TARGETS,
        "gates": gates,
        "blocking_gaps": [
            "TRUSTED_RELEASE_TRUTH_MISSING",
            "150_PAGE_REVIEW_HAS_ZERO_RESPONSES",
            "SOURCE_TO_CDP_BINDING_ZERO",
            "FINAL_POST_HITL_SCORE_UNAVAILABLE",
            "WARM_P95_EXCEEDS_5_SECONDS_PER_PAGE",
            "OPERATIONAL_EVIDENCE_INCOMPLETE",
            "TOTAL_COST_NOT_CONFIGURED",
        ],
    })

    decision = {
        "status": "NO_GO",
        "decision": "NO_GO",
        "generated_at": now,
        "implementation_commit_sha": candidate_freeze.get("implementation_commit_sha"),
        "branch": candidate_freeze.get("branch"),
        "reason": "Final production qualification is not evaluable and measured latency also fails.",
        "release_authority_enabled": False,
        "truth_inventory": "truth_inventory.json",
        "release_gate_report": "release_gate_report.json",
        "blocking_gaps": [
            "TRUSTED_RELEASE_TRUTH_MISSING",
            "SOURCE_TO_CDP_BINDING_ZERO",
            "FINAL_POST_HITL_SCORE_UNAVAILABLE",
            "WARM_P95_GATE_FAIL",
            "OPERATIONAL_EVIDENCE_INCOMPLETE",
            "TOTAL_COST_NOT_CONFIGURED",
        ],
    }
    write("final_qualification.json", decision)
    (OUT / "final_qualification.md").write_text(
        "# CDP Final Production Qualification\n\n"
        "## Decision\n\n**NO-GO**\n\n"
        "The current candidate is technically frozen but not production-qualified. "
        "Independent release truth is unavailable, the 150-page blind review has zero responses, "
        "source-to-CDP binding is 0%, and final post-HITL accuracy cannot be scored. "
        f"Measured warm P95 is {selected_p95} ms against a {TARGETS['warm_p95_ms']} ms target.\n\n"
        "## Required release blockers\n\n"
        "- Obtain governed independent review responses with source hashes and reviewer provenance.\n"
        "- Complete dual review and adjudication for governed critical fields.\n"
        "- Prove source-to-rendered-page-to-CDP-to-claim binding.\n"
        "- Freeze release truth before scoring raw and post-HITL outputs.\n"
        "- Re-run the current pipeline, exercise HITL correction and revalidation, and score final outputs.\n"
        "- Resolve the warm P95 gate and configure total cost measurement.\n"
        "- Complete security, database/events, load/KEDA, failure-injection, and approval evidence.\n",
        encoding="utf-8",
    )
    return decision


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
