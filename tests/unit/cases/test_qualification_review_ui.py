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
    rows = [{"page_id": "page", "package_id": "package", "rendered_page_sha256": "b" * 64}]
    registry = {
        "authorized_reviewers": ["one", "two"],
        "adjudicators": ["third"],
        "identity_verified": True,
        "policy_id": "synthetic-test",
    }
    (tmp_path / "blind_source_views.local.json").write_text(json.dumps(rows))
    (tmp_path / "reviewer_registry.local.json").write_text(json.dumps(registry))
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
    client.post("/qualification-review/login", data={"reviewer": "third"})
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
