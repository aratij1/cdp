"""Source-only review intake and immutable pre-truth package reservation.

This orchestrator never creates labels or grants release authority. Valid responses
remain untrusted until existing independent review/adjudication governance is met.
Detailed response and package artifacts must remain outside Git.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.claim_intelligence.document import fingerprint
from packages.hitl_reduction.review_coordination import canonical_reviewer_id
from packages.real_data_evaluation.governance import (
    assert_no_package_leakage,
    package_level_split,
)

ROOT = Path(__file__).resolve().parents[1]
METRICS = (
    "overall_accuracy",
    "critical_accuracy",
    "accepted_precision",
    "critical_accepted_precision",
    "critical_false_accepts",
    "field_hitl",
    "critical_field_hitl",
    "claim_hitl",
    "stp",
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SourceField(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field_name: str = Field(min_length=1)
    visibility: Literal["READABLE", "PARTIAL", "UNREADABLE", "ABSENT"]
    observed_value: str | None

    @model_validator(mode="after")
    def visible_value(self) -> SourceField:
        if not self.field_name.strip():
            raise ValueError("FIELD_NAME_REQUIRED")
        if self.visibility in {"UNREADABLE", "ABSENT"} and self.observed_value is not None:
            raise ValueError("UNREADABLE_OR_ABSENT_CANNOT_HAVE_VALUE")
        if self.visibility == "READABLE" and not (self.observed_value or "").strip():
            raise ValueError("READABLE_VALUE_REQUIRED")
        return self


class SourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reviewer_id: str = Field(min_length=1)
    page_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fields: list[SourceField] = Field(min_length=1)

    @model_validator(mode="after")
    def independent_identity(self) -> SourceResponse:
        if not canonical_reviewer_id(self.reviewer_id):
            raise ValueError("REVIEWER_ID_REQUIRED")
        names = [item.field_name for item in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("DUPLICATE_FIELD_RESPONSE")
        return self


def validate_blind(manifest: dict) -> None:
    if set(manifest) != {"cohort_sha256", "creates_labels", "pages"}:
        raise ValueError("BLIND_METADATA_CONTAMINATION")
    if manifest["creates_labels"] is not False:
        raise ValueError("LABEL_CREATION_FORBIDDEN")
    pages = manifest["pages"]
    if len(pages) != 150 or any(set(p) != {"page_id", "package_id"} for p in pages):
        raise ValueError("FROZEN_SOURCE_ONLY_150_REQUIRED")
    if len({p["page_id"] for p in pages}) != 150:
        raise ValueError("DUPLICATE_PAGE")


def assert_benchmark_disjoint(manifest: dict, benchmark_packages: set[str]) -> None:
    """The source-only blind set must not overlap the latency development cohort."""
    if {fingerprint(p["package_id"]) for p in manifest["pages"]} & benchmark_packages:
        raise ValueError("LATENCY_BENCHMARK_BLIND_PACKAGE_LEAKAGE")


def reserve_packages(manifest: dict, path: Path) -> dict:
    """Reserve packages before labels arrive; do not claim untouched truth freeze."""
    validate_blind(manifest)
    assignments = package_level_split(
        (p["package_id"] for p in manifest["pages"]), seed="production-closure-v1"
    )
    assert_no_package_leakage(assignments.items())
    payload = {
        "status": "PRE_TRUTH_PACKAGE_RESERVATION",
        "blind_manifest_sha256": digest(manifest),
        "assignments": assignments,
        "truth_manifest_sha256": None,
        "qualification_holdout_frozen": False,
        "untouched_attestation_required": True,
    }
    if path.exists():
        if json.loads(path.read_text("utf-8")) != payload:
            raise ValueError("IMMUTABLE_PACKAGE_RESERVATION_CHANGED")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
    return payload


def audit_responses(manifest: dict, responses: list[dict], source_bindings: dict[str, str]) -> dict:
    validate_blind(manifest)
    pages = {p["page_id"]: p["package_id"] for p in manifest["pages"]}
    seen: set[tuple[str, str]] = set()
    accepted = 0
    rejected: Counter[str] = Counter()
    for raw in responses:
        try:
            response = SourceResponse.model_validate(raw)
        except ValueError:
            rejected["INVALID_OR_PREDICTION_CONTAMINATED_RESPONSE"] += 1
            continue
        key = (response.page_id, canonical_reviewer_id(response.reviewer_id))
        if key in seen:
            rejected["DUPLICATE_REVIEWER_PAGE_RESPONSE"] += 1
            continue
        seen.add(key)
        if pages.get(response.page_id) != response.package_id:
            rejected["OUTSIDE_FROZEN_COHORT"] += 1
        elif source_bindings.get(response.page_id) != response.source_sha256:
            rejected["MISSING_OR_MISMATCHED_GOVERNED_SOURCE_BINDING"] += 1
        else:
            accepted += 1
    return {
        "submitted_responses": len(responses),
        "structurally_valid_bound_responses": accepted,
        "rejected_responses": sum(rejected.values()),
        "rejection_reasons": dict(rejected),
        "release_truth_created": 0,
        "status": "AWAITING_GOVERNED_REVIEW_FINALIZATION"
        if accepted
        else "AWAITING_INDEPENDENT_REVIEW",
        "reviewer_identity_and_source_only_attestation_required": True,
        "critical_fields_require_independent_dual_review": True,
        "disagreements_require_independent_adjudication": True,
    }


def run() -> dict:
    blind_path = ROOT / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    handoff = ROOT / "evaluation_results/closure/iteration4/human_review"
    output = ROOT / "evaluation_results/production_closure/release"
    protected = [
        blind_path,
        *(
            handoff / name
            for name in (
                "blind_manifest.json",
                "review_response_schema.json",
                "REVIEW_INSTRUCTIONS.md",
            )
        ),
    ]
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected
    }
    manifest = json.loads(blind_path.read_text("utf-8"))
    if json.loads((handoff / "blind_manifest.json").read_text("utf-8")) != manifest:
        raise ValueError("BLIND_HANDOFF_CHANGED")
    reservation = reserve_packages(manifest, output / "package_reservation.local.json")
    latency = ROOT / "evaluation_results/production_closure/latency/baseline8.local.json"
    benchmark_packages: set[str] = set()
    if latency.exists():
        profile = json.loads(latency.read_text())
        benchmark_packages = {p["package_id"] for e in profile["experiments"] for p in e["pages"]}
        assert_benchmark_disjoint(manifest, benchmark_packages)

    # Explicit approved intake only; historical synthetic/model labels are not inputs.
    response_path = handoff / "review_responses.jsonl"
    responses = (
        [json.loads(line) for line in response_path.read_text("utf-8").splitlines() if line.strip()]
        if response_path.exists()
        else []
    )
    # No source binding or reviewer identity is inferred from a response itself.
    intake = audit_responses(manifest, responses, {})
    current = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected
    }
    if current != hashes:
        raise ValueError("BLIND_HANDOFF_MUTATED")
    (output / "blind_integrity.local.json").write_text(json.dumps(hashes, indent=2), "utf-8")
    (output / "intake_audit.json").write_text(json.dumps(intake, indent=2), "utf-8")
    assignment_counts = Counter(reservation["assignments"].values())
    page_counts = Counter(reservation["assignments"][p["package_id"]] for p in manifest["pages"])
    summary = {
        "status": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
        "blind_pages": 150,
        "blind_handoff_unchanged": True,
        "predictions_in_review_view": False,
        "review_responses_received": len(responses),
        "trusted_truth_fields": 0,
        "labels_created": 0,
        "production_authority_enabled": False,
        "package_leakage_count": 0,
        "latency_benchmark_packages_checked": len(benchmark_packages),
        "latency_blind_package_overlap": 0 if benchmark_packages else None,
        "package_counts": dict(assignment_counts),
        "page_counts": dict(page_counts),
        "split_status": reservation["status"],
        "qualification_holdout_frozen": False,
        "truth_manifest_sha256": None,
        "release_targets": {
            "overall_accuracy_min": 0.98,
            "critical_accuracy_min": 0.995,
            "accepted_precision_min": 0.995,
            "critical_accepted_precision_min": 0.995,
            "critical_false_accepts_max": 0,
            "field_hitl_max": 0.10,
            "claim_hitl_max": 0.20,
            "stp_min": 0.80,
            "warm_p95_ms_max": 5000,
            "paid_ai_usd_per_page_max": 0.001,
        },
        "release_slices": {
            name: {"status": "NOT_EVALUABLE", "values": None}
            for name in ("form", "field", "quality_band", "criticality", "source")
        },
        "release_metrics": {name: {"value": None, "status": "NOT_EVALUABLE"} for name in METRICS},
        "required_external_inputs": [
            "INDEPENDENT_SOURCE_ONLY_REVIEW_RESPONSES",
            "GOVERNED_REVIEWER_IDENTITY_AND_SOURCE_BINDINGS",
            "CRITICAL_DUAL_REVIEW_AND_INDEPENDENT_ADJUDICATION",
            "UNTOUCHED_HOLDOUT_ATTESTATION",
        ],
        "existing_governance": [
            "compare_critical_annotations",
            "finalize_agreement",
            "adjudicate_critical",
            "freeze_cohort",
            "HoldoutLedger",
        ],
        "frozen_prediction_snapshot": {
            "implementation": "packages.real_data_evaluation.prediction_freeze.freeze_predictions",
            "status": "AWAITING_COMPLETE_FINAL_RUNTIME_PREDICTIONS_AND_SOURCE_BINDINGS",
            "sha256": None,
            "requires_exact_cohort_and_package_lineage": True,
            "reviewer_visible": False,
            "missing_pages_are_not_fabricated": True,
        },
        "holdout_executions": 0,
        "holdout_used_for_tuning": False,
    }
    (output / "release_scorecard.json").write_text(json.dumps(summary, indent=2), "utf-8")
    (ROOT / "docs/closure/production_release_readiness.json").write_text(
        json.dumps(summary, indent=2) + "\n", "utf-8"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
