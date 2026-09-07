"""Synthetic tests of exact binding, blind collection, governance and configured costs."""

import copy
import json
from dataclasses import replace
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from packages.real_data_evaluation.blind_workflow import FIELDS, BlindReviewStore, content_digest
from packages.real_data_evaluation.qualification_cost import Rates, Workload, calculate
from packages.real_data_evaluation.release_truth import finalize_reviews, freeze_truth
from packages.real_data_evaluation.source_binding import PageIdentity, bind_pages, complete_claims


def identity(page="source"):
    return PageIdentity(page, "a" * 64, 0, "b" * 64, "package", ("manifest",))


def test_exact_binding_uses_all_lineage_components():
    source = identity()
    cdp = replace(source, page_id="cdp")
    result = bind_pages((source,), (cdp,))[0]
    assert result.state == "EXACT" and result.cdp_page_id == "cdp" and result.claim_id is None
    for change in (
        {"source_page_index": 1},
        {"source_asset_sha256": "c" * 64},
        {"rendered_page_sha256": "d" * 64},
        {"package_id": "other"},
    ):
        assert bind_pages((source,), (replace(cdp, **change),))[0].state == "UNBOUND"


def test_reused_hash_and_conflicting_identity_fail_closed():
    source = identity()
    cdp = replace(source, page_id="cdp")
    assert bind_pages((source,), (cdp, replace(cdp, page_id="other")))[0].state == "AMBIGUOUS"
    assert bind_pages((source,), (cdp, replace(cdp, source_page_index=1)))[0].state == "AMBIGUOUS"
    with pytest.raises(ValueError):
        replace(cdp, claim_id="not-established")


def test_missing_page_excludes_entire_claim():
    source = identity()
    cdp = replace(
        source, page_id="cdp", claim_id="claim", claim_boundary_provenance="human-boundary"
    )
    binding = bind_pages((source,), (cdp,))
    assert complete_claims(binding, {"claim": frozenset({"cdp", "missing"})}) == frozenset()
    assert complete_claims(binding, {"claim": frozenset({"cdp"})}) == {"claim"}


def annotation(value="SYNTHETIC"):
    return {
        "fields": {f: {"state": "VALUE", "value": value, "region": [0, 0, 1, 1]} for f in FIELDS},
        "form": "CMS1500",
        "quality": "GOOD",
        "boundary": "UNCERTAIN",
        "prediction_visible": False,
    }


def registry():
    return {
        "authorized_reviewers": ["one", "two"],
        "adjudicators": ["third"],
        "identity_verified": True,
        "policy_id": "test-only",
    }


def review(reviewer, value="SYNTHETIC"):
    return {
        "page_id": "page",
        "reviewer_id": reviewer,
        "source_sha256": "b" * 64,
        "annotation": annotation(value),
        "reviewed_at": "2026-01-01T00:00:00Z",
    }


def sources():
    return {"page": {"package_id": "package", "rendered_page_sha256": "b" * 64}}


def test_drafts_resume_completed_reviews_immutable_and_not_self_truth(tmp_path):
    store = BlindReviewStore(tmp_path / "reviews.sqlite")
    store.save("page", "one", "b" * 64, {"fields": {}}, complete=False)
    assert BlindReviewStore(store.path).own("page", "one")["annotation"] == {"fields": {}}
    store.save("page", "one", "b" * 64, annotation(), complete=True)
    with pytest.raises(ValueError, match="IMMUTABLE"):
        store.save("page", "one", "b" * 64, annotation("CHANGED"), complete=True)
    assert finalize_reviews(store.completed(), sources(), registry())["status"] == "NOT_FROZEN"


def test_only_governed_independent_reviews_can_freeze(tmp_path):
    rows = [review("one"), review("two")]
    assert finalize_reviews(rows, sources(), {})["status"] == "NOT_FROZEN"
    truth = finalize_reviews(rows, sources(), registry())
    assert truth["status"] == "FROZEN" and len(truth["records"]) == len(FIELDS)
    path = tmp_path / "truth.json"
    freeze_truth(path, truth)
    freeze_truth(path, truth)
    changed = copy.deepcopy(truth)
    changed["records"][0]["value"] = "CHANGED"
    with pytest.raises(ValueError):
        freeze_truth(path, changed)
    with pytest.raises(ValueError, match="DUPLICATE"):
        finalize_reviews([review("one"), review(" ONE ")], sources(), registry())


def test_disagreement_requires_independent_pinned_adjudication():
    rows = [review("one"), review("two", "DIFFERENT")]
    assert finalize_reviews(rows, sources(), registry())["status"] == "NOT_FROZEN"
    decisions = [
        {
            "page_id": "page",
            "field_name": field,
            "adjudicator_id": "third",
            "review_digest": content_digest(rows),
            "conclusion": annotation()["fields"][field],
        }
        for field in FIELDS
    ]
    assert finalize_reviews(rows, sources(), registry(), decisions)["status"] == "FROZEN"
    decisions[0]["adjudicator_id"] = "one"
    assert finalize_reviews(rows, sources(), registry(), decisions)["status"] == "NOT_FROZEN"


def test_prediction_contamination_and_missing_regions_rejected(tmp_path):
    store = BlindReviewStore(tmp_path / "reviews.sqlite")
    for altered in [
        annotation() | {"prediction": "NO"},
        annotation() | {"prediction_visible": True},
    ]:
        with pytest.raises(ValueError):
            store.save("p", "one", "b" * 64, altered, complete=True)


def test_cost_unknown_rates_not_zero_and_paid_zero_usage_distinct():
    report = calculate(Workload(100, 0), Rates())
    assert report["paid_ai_cost_per_page"] == "0" and report["total_cost_per_page"] is None
    assert (
        calculate(Workload(100, 1, paid_ocr_calls=1), Rates())["paid_ai_gate"] == "NOT_CONFIGURED"
    )


def test_cost_utilization_gpu_and_authority_allocation():
    work = Workload(100, 10, Decimal(100), Decimal("0.5"), True, 0, 1000, 100, 20)
    rates = Rates(
        Decimal(1), Decimal(1), None, Decimal(1), Decimal(2), Decimal(".01"), Decimal(".001")
    )
    result = calculate(work, rates)
    assert Decimal(result["compute_cost_per_page"]) == Decimal(".04")
    assert Decimal(result["authority_cost_per_claim"]) == Decimal(".02")
    assert Decimal(result["total_cost_per_page"]) == Decimal(".043012")


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal(-1), 0.1])
def test_invalid_cost_rates_fail_closed(value):
    with pytest.raises(ValueError):
        calculate(Workload(100, 10), Rates(compute_hourly=value))


def test_blind_ui_source_preview_save_resume_and_session_isolation(tmp_path, monkeypatch):
    import hashlib

    from evaluation import qualification_closure
    from evaluation.annotation_app import qualification_review as ui
    from evaluation.reconstruct_source_bindings import rendered_hash

    source = tmp_path / "evaluation_data/source_b_1000_claims/page.tiff"
    source.parent.mkdir(parents=True)
    Image.new("L", (20, 30), 255).save(source)
    with Image.open(source) as im:
        page_hash = rendered_hash(im)
    data = tmp_path / "runtime"
    data.mkdir()
    (data / "blind_source_views.local.json").write_text(
        json.dumps(
            [
                {
                    "page_id": "page",
                    "package_id": "package",
                    "source_asset_path": str(source),
                    "frame_index": 0,
                    "source_asset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "rendered_page_sha256": page_hash,
                }
            ]
        )
    )
    monkeypatch.setattr(ui, "ROOT", tmp_path)
    monkeypatch.setattr(ui, "DATA", data)
    from tests.track_b_helpers import governed_registry

    governed_registry(tmp_path, data, monkeypatch)
    monkeypatch.setattr(qualification_closure, "refresh", lambda: None)
    app = FastAPI()
    app.include_router(ui.router)
    client = TestClient(app)
    assert client.get("/qualification-review/page/0").status_code == 401
    assert (
        client.post(
            "/qualification-review/login", data={"reviewer": "one", "access_code": "synthetic-one"}
        ).status_code
        == 200
    )
    screen = client.get("/qualification-review/page/0")
    assert "Save field" in screen.text and "Candidate class" not in screen.text
    assert client.get("/qualification-review/image/0").status_code == 200
    token = client.cookies.get("qualification_session")
    assert (
        client.post(
            "/qualification-review/draft/0", json={"annotation": annotation(), "complete": True}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/qualification-review/draft/0",
            headers={"X-Review-Session": token},
            json={"annotation": annotation(), "complete": True},
        ).status_code
        == 200
    )
    assert client.get("/qualification-review/draft/0").json()["complete"]
    second = TestClient(app)
    second.post(
        "/qualification-review/login", data={"reviewer": "two", "access_code": "synthetic-two"}
    )
    assert second.get("/qualification-review/draft/0").json()["annotation"] == {}
    assert second.get("/qualification-review/adjudication/0").status_code == 403


def snapshots():
    from packages.real_data_evaluation.release_scoring import score_release

    truth = finalize_reviews([review("one"), review("two")], sources(), registry())
    membership = {
        "governed": True,
        "boundary_provenance": "synthetic-human-review",
        "claims": {
            "claim": {
                "page_ids": ["page"],
                "package_id": "package",
                "expected_field_keys": [["page", f] for f in FIELDS],
            }
        },
    }
    raw = {
        "scope": "CANONICAL_PRODUCTION_PIPELINE",
        "used_for_tuning": False,
        "purpose": "FINAL_GATE",
        "configuration_sha256": "c" * 64,
        "execution_provenance": ["synthetic-unit-test"],
        "fields": [
            {
                "page_id": "page",
                "field_name": f,
                "state": "VALUE",
                "value": "SYNTHETIC",
                "accepted": True,
                "review_required": False,
            }
            for f in FIELDS
        ],
        "claims": {"claim": {"decision": "STP_SAFE"}},
    }
    final = copy.deepcopy(raw)
    final["claims"]["claim"] = {
        "decision": "STP_SAFE",
        "revalidation_completed": True,
        "human_corrected": True,
        "human_reviewed": True,
        "output_completed": True,
        "required_fields_pass": True,
        "required_evidence_pass": True,
    }
    raw["fields"][0].update(value="WRONG", review_required=False)
    raw["fields"][1].update(accepted=False, review_required=True)
    raw["snapshot_sha256"] = content_digest(raw)
    final["snapshot_sha256"] = content_digest(final)
    return truth, raw, final, membership, score_release


def test_raw_and_post_hitl_scores_cannot_hide_false_accepts():
    truth, raw, final, membership, score = snapshots()
    report = score(truth, raw, final, membership)
    assert report["raw"]["accuracy"] == 0.875 and report["post_hitl"]["final_accuracy"] == 1
    assert report["raw"]["critical_false_accepts"] == 1 and report["raw"]["stp"] == 0
    assert report["raw"]["claim_hitl"] == 1
    assert report["post_hitl"]["claims_closed_after_revalidation"] == 1


def test_scoring_rejects_unfrozen_truth_or_changed_denominator():
    truth, raw, final, membership, score = snapshots()
    broken = copy.deepcopy(truth)
    broken["status"] = "NOT_FROZEN"
    with pytest.raises(ValueError):
        score(broken, raw, final, membership)
    raw["fields"].pop()
    raw["snapshot_sha256"] = content_digest(
        {k: v for k, v in raw.items() if k != "snapshot_sha256"}
    )
    with pytest.raises(ValueError, match="DENOMINATOR"):
        score(truth, raw, final, membership)


def test_release_cohort_requires_complete_bound_claim_and_reserved_holdout():
    from packages.real_data_evaluation.release_cohort import build_release_cohort

    truth, _, _, membership, _ = snapshots()
    membership["complete_claim_membership_confirmed"] = True
    binding = {"source_page_id": "page", "state": "EXACT", "package_id": "package"}
    scoped, cohort = build_release_cohort(
        truth, [binding], membership, {"package": "HOLDOUT", "other": "DEVELOPMENT"}
    )
    assert cohort["source_binding_coverage"] == 1 and cohort["package_leakage"] == 0
    assert scoped["parent_truth_sha256"] == truth["truth_sha256"]
    membership["claims"]["claim"]["page_ids"].append("missing")
    with pytest.raises(ValueError, match="NO_COMPLETE_RELEASE_CLAIMS"):
        build_release_cohort(truth, [binding], membership, {"package": "HOLDOUT"})


def test_target_hardware_runner_uses_three_isolated_processes(monkeypatch, tmp_path):
    from evaluation import production_latency_qualification as target
    from tests.unit.cases.test_production_latency import profile

    # Reuse the governor's synthetic profile contract; no actual OCR or hardware claims.
    baseline = profile(6000)
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    (baseline_dir / "qualification.local.json").write_text(json.dumps(baseline))
    monkeypatch.setattr(target, "OUT", baseline_dir)
    calls = []

    def run(command, **kwargs):
        from pathlib import Path

        calls.append(command)
        value = copy.deepcopy(baseline)
        value["experiments"] = value["experiments"][:2]
        Path(command[-1]).write_text(json.dumps(value))

    monkeypatch.setattr(target.subprocess, "run", run)
    target.qualify_target(tmp_path / "target")
    assert len(calls) == 3 and all("--worker-output" in c for c in calls)


def test_final_assembler_requires_every_unwaived_gate(tmp_path, monkeypatch):
    from evaluation import final_qualification as report

    closure = {
        "blockers": [
            {"blocker_id": f"B{i}", "status": "PASS", "gate": f"gate{i}", "current_value": 1}
            for i in range(1, 17)
        ],
        "input_digest": "synthetic-test-only",
        "page_binding": {},
        "scoring": {"raw": {}, "post_hitl": {}},
        "cost": {},
    }
    monkeypatch.setattr(report, "OUT", tmp_path)
    monkeypatch.setattr(
        report, "load", lambda name: closure if name.endswith("closure_tracker.json") else {}
    )
    assert report.build()["decision"] == "GO"
    assert report.build()["release_authority_enabled"] is False
    closure["blockers"][0]["status"] = "WAIVED_NOT_ALLOWED"
    assert report.build()["decision"] == "NO_GO"
    closure["blockers"].pop(0)
    assert report.build()["decision"] == "NO_GO"


def test_concurrent_qualification_freezes_cannot_replace_inputs(tmp_path, monkeypatch):
    from evaluation import qualification_closure as workflow

    monkeypatch.setattr(workflow, "OUT", tmp_path)
    workflow.write_immutable("ledger.json", {"run": "synthetic-a"})
    workflow.write_immutable("ledger.json", {"run": "synthetic-a"})
    with pytest.raises(ValueError, match="IMMUTABLE_QUALIFICATION_INPUT_CHANGED"):
        workflow.write_immutable("ledger.json", {"run": "synthetic-b"})
    assert workflow.load(tmp_path / "ledger.json") == {"run": "synthetic-a"}
