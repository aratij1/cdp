"""Governed blind-review UI counters and adjudication work queue."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.real_data_evaluation.blind_workflow import FIELDS, content_digest
from packages.real_data_evaluation.release_truth import finalize_reviews, freeze_truth


@pytest.fixture
def review_ui(tmp_path, monkeypatch):
    from evaluation.annotation_app import qualification_review as ui

    monkeypatch.setattr(ui, "DATA", tmp_path)
    monkeypatch.setattr(ui, "ROOT", tmp_path)
    rows = [{"page_id": "page", "package_id": "package", "rendered_page_sha256": "b" * 64}]
    registry = {
        "authorized_reviewers": ["one", "two"],
        "adjudicators": ["third"],
        "identity_verified": True,
        "policy_id": "synthetic-test",
    }
    (tmp_path / "blind_source_views.local.json").write_text(json.dumps(rows))
    from tests.track_b_helpers import governed_registry

    registry = governed_registry(tmp_path, tmp_path, monkeypatch)
    annotation = {
        "fields": {
            f: {"state": "VALUE", "value": "SYNTHETIC", "region": [0, 0, 1, 1]} for f in FIELDS
        },
        "form": "CMS1500",
        "quality": "GOOD",
        "boundary": "START_CLAIM",
        "prediction_visible": False,
    }
    for reviewer in ["one", "two"]:
        ui.store().save("page", reviewer, "b" * 64, annotation, complete=True)
    app = FastAPI()
    app.include_router(ui.router)
    client = TestClient(app)
    client.post(
        "/qualification-review/login", data={"reviewer": "third", "access_code": "synthetic-third"}
    )
    return ui, client, rows, registry


def test_progress_preserves_authoritative_file_and_uses_sealed_truth(review_ui):
    ui, client, rows, registry = review_ui
    authoritative = ui.DATA / "review_completion_status.json"
    authoritative.write_text('{"watcher_owned":true}')
    report = client.get("/qualification-review/progress").json()
    assert report["trusted_labels"] == 0
    assert report["critical_fields_dual_reviewed"] == len(FIELDS)
    truth = finalize_reviews(ui.store().completed(), {r["page_id"]: r for r in rows}, registry)
    freeze_truth(ui.DATA / "release_truth_manifest.local.json", truth)
    report = client.get("/qualification-review/progress").json()
    assert report["trusted_labels"] == len(FIELDS)
    assert report["truth_status"] == "FROZEN"
    assert authoritative.read_text() == '{"watcher_owned":true}'
    truth["records"][0]["value"] = "TAMPERED"
    (ui.DATA / "release_truth_manifest.local.json").write_text(json.dumps(truth))
    assert client.get("/qualification-review/progress").json()["trusted_labels"] == 0


def test_adjudication_queue_excludes_agreed_and_resolved_pages(review_ui):
    ui, client, _, _ = review_ui
    assert "/adjudication/0" not in client.get("/qualification-review/adjudication-queue").text
    # Synthetic fixture changes one completed row directly to model an independent disagreement.
    with ui.store().connect() as db:
        payload = json.loads(
            db.execute("SELECT payload FROM reviews WHERE reviewer='two'").fetchone()[0]
        )
        payload["fields"][FIELDS[0]]["value"] = "DIFFERENT"
        db.execute("UPDATE reviews SET payload=? WHERE reviewer='two'", (json.dumps(payload),))
    assert "/adjudication/0" in client.get("/qualification-review/adjudication-queue").text
    reviews = ui.store().completed()
    ui.store().adjudicate(
        "page",
        FIELDS[0],
        "third",
        content_digest(reviews),
        reviews[0]["annotation"]["fields"][FIELDS[0]],
    )
    assert "/adjudication/0" not in client.get("/qualification-review/adjudication-queue").text
    assert client.get("/qualification-review/progress").json()["adjudications"] == 1


def test_adjudication_digest_uses_only_governed_reviewers(review_ui):
    ui, client, _, _ = review_ui
    governed = ui.store().completed()
    ui.store().save("page", "unverified", "b" * 64, governed[0]["annotation"], complete=True)
    screen = client.get("/qualification-review/adjudication/0")
    assert screen.status_code == 200
    assert content_digest(governed) in screen.text
    assert content_digest(ui.store().completed()) not in screen.text


def test_second_review_queue_preserves_independence_and_hides_observations(review_ui):
    ui, client, _, _ = review_ui
    with ui.store().connect() as db:
        db.execute("DELETE FROM reviews WHERE reviewer='two'")
    client.post(
        "/qualification-review/login", data={"reviewer": "one", "access_code": "synthetic-one"}
    )
    assert "/page/0" not in client.get("/qualification-review/second-review-queue").text
    client.post(
        "/qualification-review/login", data={"reviewer": "two", "access_code": "synthetic-two"}
    )
    result = client.get("/qualification-review/second-review-queue")
    assert result.status_code == 200 and "/page/0" in result.text
    assert "SYNTHETIC" not in result.text
    assert (
        client.post("/qualification-review/login", data={"reviewer": "unverified"}).status_code
        == 403
    )


def test_completion_tracker_reports_coverage_and_effort_without_invented_minutes(review_ui):
    _, client, _, _ = review_ui
    result = client.get("/qualification-review/progress").json()
    assert result["remaining_independent_page_reviews"] == 0
    assert result["estimated_remaining_review_minutes"] is None
    assert len(result["reviewer_completion"]) == 2
    assert all(r["completion_rate"] == 1 for r in result["reviewer_completion"].values())
    assert "one" not in result["reviewer_completion"]


def test_trusted_review_counts_do_not_freeze_release_truth(review_ui):
    ui, client, _, _ = review_ui
    result = client.get("/qualification-review/progress").json()
    assert result["trusted_fields"] == len(FIELDS)
    assert result["trusted_review_pages"] == 1
    assert result["trusted_labels"] == 0
    assert not (ui.DATA / "release_truth_manifest.local.json").exists()
