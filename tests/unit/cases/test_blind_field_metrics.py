"""Partial field measurement reuses independent truth without inventing claims."""

import json
from copy import deepcopy

import pytest

from evaluation.blind_field_metrics import build, evaluate
from packages.real_data_evaluation.blind_workflow import FIELDS, content_digest


def sample():
    sources = {"page": {"package_id": "package", "rendered_page_sha256": "a" * 64}}
    annotation = {
        "fields": {
            f: {"state": "VALUE", "value": "SYNTHETIC", "region": [0, 0, 1, 1]} for f in FIELDS
        },
        "form": "CMS1500",
        "quality": "GOOD",
        "boundary": "UNCERTAIN",
        "prediction_visible": False,
    }
    reviews = [
        {
            "page_id": "page",
            "reviewer_id": r,
            "source_sha256": "a" * 64,
            "annotation": deepcopy(annotation),
        }
        for r in ("one", "two")
    ]
    registry = {
        "identity_verified": True,
        "policy_id": "TEST",
        "authorized_reviewers": ["one", "two"],
    }
    candidate = {"candidate_commit_sha": "b" * 40}
    settings = {
        "pipeline_configuration_sha256": "c" * 64,
        "deployment_attestation_sha256": "d" * 64,
    }
    raw = {
        "scope": "CANONICAL_PRODUCTION_PIPELINE",
        "purpose": "FINAL_GATE",
        "used_for_tuning": False,
        "candidate_commit_sha": candidate["candidate_commit_sha"],
        "configuration_sha256": "c" * 64,
        "fields": [
            {
                "page_id": "page",
                "field_name": f,
                "package_id": "package",
                "source_sha256": "a" * 64,
                "document_id": "doc",
                "source_binding": "EXACT",
                "prediction_binding": "EXACT",
                "state": "VALUE",
                "value": "SYNTHETIC",
                "accepted": True,
                "review_required": False,
            }
            for f in FIELDS
        ],
        "execution_provenance": [
            {
                "document_id": "doc",
                "candidate_commit_sha": "b" * 40,
                "deployment_attestation_sha256": "d" * 64,
                "decision_event_id": "event",
                "source_pages": [{"page_id": "page", "rendered_page_sha256": "a" * 64}],
            }
        ],
    }
    seal(raw)
    return {
        "sources": sources,
        "reviews": reviews,
        "registry": registry,
        "adjudications": [],
        "raw": raw,
        "candidate": candidate,
        "settings": settings,
        "prerequisite_gate": None,
        "deployment_gate": None,
    }


def seal(raw):
    raw["snapshot_sha256"] = content_digest(
        {k: v for k, v in raw.items() if k != "snapshot_sha256"}
    )


def test_partial_fields_need_no_claim_membership_or_full_cohort_truth():
    args = sample()
    args["sources"]["unreviewed-page"] = {
        "package_id": "package2",
        "rendered_page_sha256": "e" * 64,
    }
    original = deepcopy(args)
    result = evaluate(**args)
    assert args == original
    assert result["status"] == "PARTIAL_FIELD_METRICS_AVAILABLE"
    assert result["metrics"]["raw_accuracy"] == {
        "numerator": 8,
        "denominator": 8,
        "percentage": 100,
    }
    assert result["trusted_pages"] == 1 and result["pages"] == 2
    assert result["claim_hitl"]["status"] == result["true_stp"]["status"] == "NOT_EVALUABLE"
    assert result["final_release_qualification"] is False
    assert "SYNTHETIC" not in json.dumps(result)


def test_no_reviews_means_null_metrics_not_zero_accuracy():
    args = sample()
    args["reviews"] = []
    result = evaluate(**args)
    assert "NO_TRUSTED_FIELD_REVIEWS" in result["gates"]
    assert result["metrics"]["raw_accuracy"]["denominator"] is None


@pytest.mark.parametrize("change", ["single_reviewer", "unverified_registry", "disagreement"])
def test_trust_requires_independent_governed_complete_page(change):
    args = sample()
    if change == "single_reviewer":
        args["reviews"] = args["reviews"][:1]
    elif change == "unverified_registry":
        args["registry"]["identity_verified"] = False
    else:
        args["reviews"][1]["annotation"]["fields"][FIELDS[0]]["value"] = "different"
    result = evaluate(**args)
    assert result["trusted_fields"] == 0
    assert result["status"] == "NOT_EVALUABLE"


@pytest.mark.parametrize(
    "change",
    [
        "candidate",
        "seal",
        "tuning",
        "source",
        "provenance",
        "duplicate",
        "missing",
        "human_corrected",
    ],
)
def test_invalid_execution_never_scores(change):
    args = sample()
    raw = args["raw"]
    if change == "candidate":
        raw["candidate_commit_sha"] = "f" * 40
    elif change == "seal":
        raw["configuration_sha256"] = "broken"
    elif change == "tuning":
        raw["used_for_tuning"] = True
    elif change == "source":
        raw["fields"][0]["source_sha256"] = "f" * 64
    elif change == "provenance":
        raw["execution_provenance"][0]["source_pages"] = []
    elif change == "duplicate":
        raw["fields"].append(deepcopy(raw["fields"][0]))
    elif change == "missing":
        raw["fields"].pop()
    elif change == "human_corrected":
        raw["fields"][0]["human_corrected"] = True
    if change != "seal":
        seal(raw)
    result = evaluate(**args)
    assert result["status"] == "NOT_EVALUABLE"
    assert result["metrics"]["raw_accuracy"]["denominator"] is None


def test_accepted_precision_excludes_human_route_and_counts_false_accept():
    args = sample()
    raw = args["raw"]
    raw["fields"][0]["value"] = "WRONG"
    raw["fields"][1]["review_required"] = True
    seal(raw)
    result = evaluate(**args)
    assert result["metrics"]["raw_accuracy"]["numerator"] == 7
    assert result["metrics"]["accepted_precision"]["denominator"] == 7
    assert result["metrics"]["accepted_precision"]["numerator"] == 6
    assert result["metrics"]["field_hitl"] == {"numerator": 1, "denominator": 8, "percentage": 12.5}
    assert result["critical_false_accepts"] == 1


def test_existing_comparator_normalizes_amounts():
    args = sample()
    for r in args["reviews"]:
        r["annotation"]["fields"]["total_charge"]["value"] = "$1,000.00"
    next(r for r in args["raw"]["fields"] if r["field_name"] == "total_charge")["value"] = "1000.00"
    seal(args["raw"])
    assert evaluate(**args)["metrics"]["raw_accuracy"]["numerator"] == 8


def test_missing_inputs_publish_gates_without_creating_review_db(tmp_path):
    result = build(tmp_path)
    assert result["status"] == "NOT_EVALUABLE"
    assert not (
        tmp_path / "evaluation_results/qualification_closure/blind_reviews.sqlite3"
    ).exists()
    assert "CANONICAL_RAW_SNAPSHOT_REQUIRED" in result["gates"]


def test_build_preserves_reserved_holdout_denominator(tmp_path):
    import hashlib

    private = tmp_path / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    sources = [
        {"page_id": name, "package_id": package, "rendered_page_sha256": "a" * 64}
        for name, package in (
            ("holdout", "holdout-package"),
            ("development", "development-package"),
        )
    ]
    manifest = {
        "pages": [{"page_id": s["page_id"], "package_id": s["package_id"]} for s in sources]
    }
    manifest_path = tmp_path / "evaluation_results/cdp2/active_learning_blind_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest))
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    bindings = {
        "blind_manifest_sha256": manifest_hash,
        "bindings": [
            {
                "source_page_id": s["page_id"],
                "package_id": s["package_id"],
                "cdp_page_id": s["page_id"],
                "state": "EXACT",
                "rendered_page_sha256": "a" * 64,
                "cdp_page_sha256": "a" * 64,
            }
            for s in sources
        ],
    }
    reservation = {
        "assignments": {"holdout-package": "HOLDOUT", "development-package": "DEVELOPMENT"},
        "blind_manifest_sha256": content_digest(manifest),
    }
    reservation_path = (
        tmp_path / "evaluation_results/production_closure/release/package_reservation.local.json"
    )
    reservation_path.parent.mkdir(parents=True)
    reservation_path.write_text(json.dumps(reservation))
    for name, payload in (
        ("blind_source_views.local.json", sources),
        ("source_page_bindings.local.json", bindings),
        (
            "binding_reservation_freeze.local.json",
            {
                "bindings_sha256": content_digest(bindings),
                "reservation_sha256": content_digest(reservation),
                "manifest_sha256": manifest_hash,
            },
        ),
    ):
        (private / name).write_text(json.dumps(payload))
    result = build(tmp_path)
    assert result["cohort_pages"] == 2
    assert result["eligible_holdout_pages"] == result["excluded_development_pages"] == 1
    assert "FROZEN_BINDING_RESERVATION_SEAL_REQUIRED" not in result["gates"]
    (private / "binding_reservation_freeze.local.json").write_text("{}")
    assert "FROZEN_BINDING_RESERVATION_SEAL_REQUIRED" in build(tmp_path)["gates"]
