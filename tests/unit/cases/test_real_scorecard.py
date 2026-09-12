"""Synthetic validation of reporting, never real human labels or production evidence."""

import copy
import json

import pytest

from evaluation.real_release import build
from packages.real_data_evaluation.blind_workflow import (
    FieldAnnotation,
    content_digest,
    review_progress,
)
from packages.real_data_evaluation.real_scorecard import build_scorecard, interval
from packages.real_data_evaluation.release_truth import finalize_reviews
from tests.unit.cases.test_qualification_closure_inputs import (
    registry,
    review,
    snapshots,
    sources,
)


def test_wilson_small_and_empty_denominators():
    assert interval(None, None)["status"] == "NOT_EVALUABLE"
    assert interval(0, 0)["status"] == "NOT_EVALUABLE"
    result = interval(10, 10)
    assert 0.72 < result["lower"] < 0.73 and result["upper"] == 1
    with pytest.raises(ValueError):
        interval(11, 10)


def test_absent_truth_does_not_invent_zero_metrics():
    card = build_scorecard({"scoring": {}}, {}, {})
    assert card["status"] == "EXTERNAL_INPUT_REQUIRED"
    assert card["final_decision"] == "PENDING_REVIEW"
    for row in card["rows"][:11]:
        assert row["numerator"] is row["denominator"] is row["value"] is None


def test_blank_and_conflict_observations_do_not_require_invented_values():
    for state in ("BLANK", "SOURCE_CONFLICT"):
        result = FieldAnnotation(state=state, value=None, region=(0, 0, 1, 1))
        assert result.value is None
        with pytest.raises(ValueError):
            FieldAnnotation(state=state, value="invented", region=(0, 0, 1, 1))


def test_review_agreement_uses_governed_name_comparator_and_unique_fields():
    one, two = review("one"), review("two")
    one["annotation"]["fields"]["patient_name"]["value"] = "DOE, JANE"
    two["annotation"]["fields"]["patient_name"]["value"] = "doe jane"
    truth = finalize_reviews([one, two], sources(), registry())
    assert truth["status"] == "FROZEN"
    progress = review_progress(
        [one, two, review("unregistered")], {"page": "b" * 64}, frozenset({"one", "two"})
    )
    assert progress["agreements"] == 8
    assert progress["fields_reviewed"] == 8 and progress["review_observations"] == 16
    assert progress["pages_remaining"] == 0


def prepared(tmp_path):
    truth, raw, final, membership, score = snapshots()
    membership["complete_claim_membership_confirmed"] = True
    claim = membership["claims"]["claim"]
    claim.update(
        documents={
            "document": {
                "page_ids": ["page"],
                "boundary": "CONFIRMED",
                "boundary_provenance": "test",
            }
        },
        claim_form_page_ids=["page"],
        attachment_page_ids=[],
    )
    raw["fields"] = copy.deepcopy(final["fields"])
    flags = {
        "decision": "STP_SAFE",
        "semantic_authority_pass": True,
        "human_corrected": False,
        "human_reviewed": False,
        "output_completed": True,
        "automatic_output_safely_generated": True,
        "required_fields_pass": True,
        "required_evidence_pass": True,
    }
    raw["claims"]["claim"] = flags
    final["claims"]["claim"] = dict(flags)
    for snapshot in (raw, final):
        for field in snapshot["fields"]:
            field.update(source_sha256="b" * 64, package_id="package", claim_id="claim")
        snapshot["candidate_commit_sha"] = "a" * 40
        snapshot["snapshot_sha256"] = content_digest(
            {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
        )
    scored = score(truth, raw, final, membership)
    scored["candidate_commit_sha"] = "a" * 40
    candidate = {"candidate_commit_sha": "a" * 40}
    closure = {
        "scoring": scored,
        "freeze_integrity": {"status": "PASS", "exact_binding": True},
        "review": {"pages_total": 1, "pages_reviewed": 0},
        "page_binding": {"bound_page_count": 1, "source_page_count": 1},
    }
    data = {
        "closure_tracker.json": closure,
        "candidate_freeze.local.json": candidate,
        "claim_membership.local.json": membership,
        "release_cohort.local.json": membership,
        "scored_release_truth.local.json": truth,
        "raw_predictions.local.json": raw,
        "source_page_bindings.local.json": {
            "bindings": [
                {
                    "source_page_id": "page",
                    "cdp_page_id": "cdp",
                    "state": "EXACT",
                    "rendered_page_sha256": "b" * 64,
                    "cdp_page_sha256": "b" * 64,
                    "package_id": "package",
                }
            ]
        },
    }
    private = tmp_path / "evaluation_results/qualification_closure"
    private.mkdir(parents=True)
    for name, value in data.items():
        (private / name).write_text(json.dumps(value))
    return private, closure


def test_publisher_reconciles_counts_and_keeps_source_values_private(tmp_path):
    private, closure = prepared(tmp_path)
    card = build(tmp_path)
    assert card["rows"][0]["numerator"] == card["rows"][0]["denominator"] == 8
    assert card["rows"][8]["value"] == 1
    out = tmp_path / "evaluation_results/real_release"
    assert json.loads((out / "denominator_reconciliation.json").read_text())["status"] == "PASS"
    assert json.loads((out / "release_truth_manifest.json").read_text())["status"] == "FROZEN"
    for path in out.glob("*.json"):
        assert "SYNTHETIC" not in path.read_text()
    first = (out / "release_truth_manifest.json").read_bytes()
    build(tmp_path)
    assert (out / "release_truth_manifest.json").read_bytes() == first
    closure["scoring"]["raw"]["stp_claims"] = 0
    (private / "closure_tracker.json").write_text(json.dumps(closure))
    assert build(tmp_path)["real_metrics_evaluable"] is False


def test_wrong_candidate_or_missing_output_evidence_cannot_publish_stp(tmp_path):
    private, closure = prepared(tmp_path)
    closure["scoring"]["candidate_commit_sha"] = "different"
    (private / "closure_tracker.json").write_text(json.dumps(closure))
    card = build(tmp_path)
    assert card["real_metrics_evaluable"] is False
    assert card["rows"][8]["value"] is None


def test_invalid_current_inputs_never_rewrite_frozen_truth(tmp_path):
    private, closure = prepared(tmp_path)
    build(tmp_path)
    path = tmp_path / "evaluation_results/real_release/release_truth_manifest.json"
    before = path.read_bytes()
    closure["freeze_integrity"]["status"] = "FAIL"
    (private / "closure_tracker.json").write_text(json.dumps(closure))
    result = build(tmp_path)
    assert not result["real_metrics_evaluable"]
    assert not result["truth_usable_for_current_run"]
    assert path.read_bytes() == before


def test_checkpoint_evidence_rejects_changed_measurement_code(tmp_path, monkeypatch):
    import hashlib

    from evaluation import real_release

    module = tmp_path / "measurement.py"
    module.write_text("verified code")
    monkeypatch.setattr(real_release, "VALIDATED_MODULES", ("measurement.py",))
    stamp = {
        "status": "PASS",
        "code_sha256": {"measurement.py": hashlib.sha256(module.read_bytes()).hexdigest()},
        "checks": {"comparison_logic": True, "denominators": True, "qualification_machinery": True},
    }
    (tmp_path / "measurement_validation.local.json").write_text(json.dumps(stamp))
    assert real_release.validated_machinery(tmp_path, tmp_path) == stamp["checks"]
    module.write_text("changed code")
    assert real_release.validated_machinery(tmp_path, tmp_path) == {}
