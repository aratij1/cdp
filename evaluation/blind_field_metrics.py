"""Preliminary trusted page/field qualification; never final release or claim metrics."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from packages.claim_intelligence.normalization import comparison_key
from packages.real_data_evaluation.blind_workflow import content_digest
from packages.real_data_evaluation.closure_control import freeze_prerequisites
from packages.real_data_evaluation.release_truth import finalize_reviews

ROOT = Path(__file__).resolve().parents[1]
METRICS = (
    "raw_accuracy",
    "critical_accuracy",
    "accepted_precision",
    "critical_accepted_precision",
    "field_hitl",
)


def metric(numerator=None, denominator=None) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percentage": 100 * numerator / denominator if denominator else None,
    }


def evaluate(
    sources: dict,
    reviews: list[dict],
    registry: dict,
    adjudications: list[dict],
    raw: dict,
    candidate: dict,
    settings: dict,
    *,
    prerequisite_gate: str | None,
    deployment_gate: str | None,
) -> dict:
    result: dict = {
        "scope": "PARTIAL_FIELD_QUALIFICATION",
        "status": "NOT_EVALUABLE",
        "final_release_qualification": False,
        "claim_membership_required": False,
        "claim_hitl": {"status": "NOT_EVALUABLE"},
        "true_stp": {"status": "NOT_EVALUABLE"},
        "pages": len(sources),
        "trusted_pages": 0,
        "trusted_fields": 0,
        "scored_pages": 0,
        "scored_fields": 0,
        "critical_false_accepts": None,
        "metrics": {name: metric() for name in METRICS},
        "gates": [],
    }
    gates = result["gates"]
    if prerequisite_gate:
        gates.append(prerequisite_gate)
    truth = []
    if not prerequisite_gate:
        for page, source in sources.items():
            finalized = finalize_reviews(
                [r for r in reviews if r["page_id"] == page],
                {page: source},
                registry,
                [a for a in adjudications if a["page_id"] == page],
            )
            if finalized["status"] == "FROZEN":
                truth.extend(finalized["records"])
                result["trusted_pages"] += 1
    result["trusted_fields"] = len(truth)
    if not truth:
        gates.append("NO_TRUSTED_FIELD_REVIEWS")
    if deployment_gate:
        gates.append(deployment_gate)
    if not raw:
        gates.append("CANONICAL_RAW_SNAPSHOT_REQUIRED")
    elif (
        raw.get("scope") != "CANONICAL_PRODUCTION_PIPELINE"
        or raw.get("purpose") != "FINAL_GATE"
        or raw.get("used_for_tuning") is not False
        or not candidate.get("candidate_commit_sha")
        or raw.get("candidate_commit_sha") != candidate.get("candidate_commit_sha")
        or not settings.get("pipeline_configuration_sha256")
        or raw.get("configuration_sha256") != settings.get("pipeline_configuration_sha256")
        or not raw.get("execution_provenance")
        or raw.get("snapshot_sha256")
        != content_digest({k: v for k, v in raw.items() if k != "snapshot_sha256"})
    ):
        gates.append("CANONICAL_RAW_SNAPSHOT_INVALID")
    if gates:
        return result
    index = {(r["page_id"], r["field_name"]): r for r in raw.get("fields", [])}
    keys = {(r["page_id"], r["field_name"]) for r in truth}
    if len(index) != len(raw.get("fields", [])) or not keys <= set(index):
        gates.append("COMPLETE_TRUSTED_FIELD_PREDICTIONS_REQUIRED")
        return result
    # Additional fields on unreviewed cohort pages are allowed; other cohorts are never joined.
    if any(p not in sources for p, _ in index):
        gates.append("FOREIGN_COHORT_PREDICTIONS_FORBIDDEN")
        return result
    for observation in truth:
        page, field = observation["page_id"], observation["field_name"]
        prediction = index[(page, field)]
        provenance = [
            p
            for p in raw["execution_provenance"]
            if p.get("document_id") == prediction.get("document_id")
            and p.get("candidate_commit_sha") == candidate["candidate_commit_sha"]
            and p.get("deployment_attestation_sha256")
            == settings.get("deployment_attestation_sha256")
            and p.get("decision_event_id")
            and {"page_id": page, "rendered_page_sha256": observation["source_sha256"]}
            in p.get("source_pages", [])
        ]
        if (
            prediction.get("source_sha256") != observation["source_sha256"]
            or prediction.get("package_id") != sources[page]["package_id"]
            or prediction.get("source_binding") != "EXACT"
            or prediction.get("prediction_binding") != "EXACT"
            or not prediction.get("document_id")
            or len(provenance) != 1
            or any(
                type(prediction.get(flag)) is not bool for flag in ("accepted", "review_required")
            )
            or any(
                flag in prediction and type(prediction[flag]) is not bool
                for flag in ("human_corrected", "human_reviewed", "human_intervention_required")
            )
            or "state" not in prediction
            or "value" not in prediction
        ):
            gates.append("EXACT_CANONICAL_FIELD_OBSERVATION_REQUIRED")
            return result
        if (
            prediction.get("human_corrected") is True
            or prediction.get("authority") == "HUMAN_CONFIRMED"
        ):
            gates.append("RAW_CAPTURE_AFTER_HUMAN_CORRECTION_FORBIDDEN")
            return result

    def correct(row):
        pred = index[(row["page_id"], row["field_name"])]
        if row["state"] != pred["state"]:
            return False
        if row["state"] != "VALUE":
            return row["value"] is None and pred["value"] is None
        return comparison_key(row["field_name"], row["value"]) == comparison_key(
            row["field_name"], pred["value"]
        )

    def routed(row):
        pred = index[(row["page_id"], row["field_name"])]
        return pred["review_required"] or any(
            pred.get(f) is True
            for f in ("human_corrected", "human_reviewed", "human_intervention_required")
        )

    critical = [r for r in truth if r["critical"]]
    accepted = [
        r for r in truth if index[(r["page_id"], r["field_name"])]["accepted"] and not routed(r)
    ]
    critical_accepted = [r for r in accepted if r["critical"]]
    for name, subset in (
        ("raw_accuracy", truth),
        ("critical_accuracy", critical),
        ("accepted_precision", accepted),
        ("critical_accepted_precision", critical_accepted),
    ):
        result["metrics"][name] = metric(sum(correct(r) for r in subset), len(subset))
    result["metrics"]["field_hitl"] = metric(sum(routed(r) for r in truth), len(truth))
    result.update(
        status="PARTIAL_FIELD_METRICS_AVAILABLE",
        scored_fields=len(truth),
        scored_pages=len({r["page_id"] for r in truth}),
        critical_false_accepts=sum(not correct(r) for r in critical_accepted),
        candidate_commit_sha=candidate["candidate_commit_sha"],
        snapshot_sha256=raw["snapshot_sha256"],
    )
    return result


def _load(path: Path, default=None):
    return (
        json.loads(path.read_text(encoding="utf-8"))
        if path.is_file()
        else ({} if default is None else default)
    )


def _reviews(path: Path) -> tuple[list[dict], list[dict]]:
    if not path.is_file():
        return [], []
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = [
            {
                "page_id": p,
                "reviewer_id": r,
                "source_sha256": s,
                "annotation": json.loads(a),
                "reviewed_at": t,
            }
            for p, r, s, a, t in db.execute(
                "SELECT page,reviewer,source_hash,payload,updated FROM reviews WHERE completed=1 ORDER BY page,reviewer"
            )
        ]
        decisions = [
            json.loads(r[0])
            for r in db.execute("SELECT payload FROM adjudications ORDER BY page,field")
        ]
    return rows, decisions


def build(root: Path = ROOT) -> dict:
    from evaluation.real_release import publish

    directory = root / "evaluation_results/qualification_closure"
    sources = {s["page_id"]: s for s in _load(directory / "blind_source_views.local.json", [])}
    manifest_path = root / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    manifest = _load(manifest_path)
    manifest_hash = (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.is_file() else ""
    )
    bindings = _load(directory / "source_page_bindings.local.json")
    reservation = _load(
        root / "evaluation_results/production_closure/release/package_reservation.local.json"
    )
    prerequisite = freeze_prerequisites(sources, bindings, reservation, manifest_hash, manifest)
    gate = None if prerequisite["status"] == "PASS" else "EXACT_RESERVED_SOURCE_BINDING_REQUIRED"
    eligible_sources = {
        page: source
        for page, source in sources.items()
        if reservation.get("assignments", {}).get(source["package_id"]) == "HOLDOUT"
    }
    seals = _load(directory / "binding_reservation_freeze.local.json")
    if seals != {
        "bindings_sha256": content_digest(bindings),
        "reservation_sha256": content_digest(reservation),
        "manifest_sha256": manifest_hash,
    }:
        gate = "FROZEN_BINDING_RESERVATION_SEAL_REQUIRED"
    config = _load(directory / "deployment_control.local.json")
    settings = config.get("cdp_services", {})
    deployment_gate: str | None = "GOVERNED_CANDIDATE_DEPLOYMENT_REQUIRED"
    raw = _load(directory / "raw_predictions.local.json")
    if raw and config.get("governed") is True and settings.get("qualification_environment") is True:
        from evaluation.deployment_control_executor import validate_candidate_deployment

        try:
            validate_candidate_deployment(settings, directory)
            deployment_gate = None
        except ValueError:
            deployment_gate = "GOVERNED_CANDIDATE_DEPLOYMENT_INVALID"
    try:
        rows, decisions = _reviews(directory / "blind_reviews.sqlite3")
        result = evaluate(
            eligible_sources,
            rows,
            _load(directory / "reviewer_registry.local.json"),
            decisions,
            raw,
            _load(directory / "candidate_freeze.local.json"),
            settings,
            prerequisite_gate=gate,
            deployment_gate=deployment_gate,
        )
    except (ValueError, KeyError, TypeError, sqlite3.DatabaseError):
        result = {
            "scope": "PARTIAL_FIELD_QUALIFICATION",
            "status": "NOT_EVALUABLE",
            "final_release_qualification": False,
            "gates": ["INVALID_FIELD_QUALIFICATION_INPUT"],
            "metrics": {name: metric() for name in METRICS},
        }
    result.update(
        cohort_pages=len(sources),
        eligible_holdout_pages=len(eligible_sources),
        excluded_development_pages=sum(
            reservation.get("assignments", {}).get(s["package_id"]) == "DEVELOPMENT"
            for s in sources.values()
        ),
        denominator_scope="TRUSTED_FIELDS_ON_RESERVED_HOLDOUT_PAGES",
    )
    publish(root / "evaluation_results/real_release/blind_field_metrics.json", result)
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
