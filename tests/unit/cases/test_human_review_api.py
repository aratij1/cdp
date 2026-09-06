"""Human review API: failed-field-only review, RBAC enforcement, and
correction/rejection persistence -- against an in-memory SQLite DB and the
Phase 1 `FakeObjectStore` test double, no Docker required."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.human_review_api.db.repository import ReviewTaskRepository
from apps.human_review_api.db.session import make_session_factory
from apps.human_review_api.main import app, get_object_store, get_session_factory
from apps.human_review_api.service import ReviewService, ReviewTaskNotOpenError
from packages.domain.common import ObjectRef
from packages.domain.enums import ReviewTaskStatus
from packages.domain.review import ReviewTask
from tests.conftest import FakeObjectStore


@pytest.fixture
def session_factory():
    factory = make_session_factory("sqlite:///:memory:")
    # apps.human_review_api.main resolves patient names with a raw SQL
    # SELECT against the `extracted_fields` table (deliberately avoiding an
    # ORM import from apps.ingestion_api -- see main.py's patient-name
    # lookup). That table lives under ingestion_api's own DeclarativeBase,
    # which this fixture's create_all() (scoped to human_review_api's Base)
    # never provisions -- create it too on the same shared in-memory
    # engine so the raw SQL has a real table to query, matching the shared
    # Postgres topology in docker-compose.
    from apps.ingestion_api.db.models import Base as IngestionBase

    IngestionBase.metadata.create_all(factory.kw["bind"])
    return factory


def _seed_extracted_field(session_factory, *, document_id, field_name, value, field_id=None) -> None:
    """Insert a real ExtractedFieldORM row via the ORM so document_id is
    stored exactly as SQLAlchemy's Uuid type would store it in production
    (hex-no-dashes on SQLite) -- proves the raw-SQL patient-name lookup in
    main.py actually matches, not just that it doesn't crash."""
    from datetime import UTC, datetime

    from apps.ingestion_api.db.models import ExtractedFieldORM

    with session_factory() as session:
        session.add(
            ExtractedFieldORM(
                field_id=field_id or uuid4(),
                document_id=document_id,
                field_name=field_name,
                raw_value=value,
                normalized_value=value,
                confidence=0.95,
                page_number=1,
                bounding_box={"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                extraction_method="REGIONAL_PADDLEOCR",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()


@pytest.fixture
def object_store():
    return FakeObjectStore()


@pytest.fixture
def client(session_factory, object_store, monkeypatch, tmp_path):
    # The repo-root .env (written for the Docker Compose validation, not
    # committed) points DATABASE_URL at the docker-internal "postgres"
    # hostname; pydantic-settings loads it regardless of dependency
    # overrides, which only affect route-level Depends(), not the
    # lifespan. Override the env vars the lifespan reads *before*
    # constructing TestClient so it never attempts that connection.
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("CORRECTION_MEMORY_PATH", str(tmp_path / "corrections.jsonl"))
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_object_store] = lambda: object_store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _seed_task(session_factory, **overrides) -> ReviewTask:
    defaults = {
        "claim_id": uuid4(),
        "document_id": uuid4(),
        "field_id": uuid4(),
        "field_name": "provider_npi",
        "page_number": 1,
        "crop_object": ObjectRef(bucket="idp-documents", key="crops/npi.png"),
        "ocr_candidates": ["1234567890", "1234567893"],
        "validation_errors": ["fails NPI checksum"],
    }
    defaults.update(overrides)
    task = ReviewTask(**defaults)
    with session_factory() as session:
        ReviewTaskRepository(session).add(task)
        session.commit()
    return task


REVIEWER_HEADERS = {"X-User-Role": "reviewer"}
VIEWER_HEADERS = {"X-User-Role": "viewer"}


def test_metrics_endpoint_exposes_prometheus_text_format(client, session_factory):
    task = _seed_task(session_factory)
    client.post(
        f"/review-tasks/{task.task_id}/reject",
        headers=REVIEWER_HEADERS,
        json={"reason": "test"},
    )
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "human_review_total" in response.text


# --- JSON API -----------------------------------------------------------------


def test_list_review_tasks_requires_permission(client):
    response = client.get("/review-tasks", headers=VIEWER_HEADERS)
    assert response.status_code == 403


def test_list_review_tasks_returns_open_tasks_only(client, session_factory):
    _seed_task(session_factory)
    response = client.get("/review-tasks", headers=REVIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["field_name"] == "provider_npi"
    assert body[0]["status"] == "OPEN"


def test_correction_promotion_candidates_start_empty(client):
    response = client.get("/correction-promotion-candidates", headers=REVIEWER_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_get_review_task_includes_signed_crop_url(client, session_factory):
    task = _seed_task(session_factory)
    response = client.get(f"/review-tasks/{task.task_id}", headers=REVIEWER_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert (
        body["crop_signed_url"]
        == "https://fake-object-store.local/idp-documents/crops/npi.png?signed=1"
    )
    assert body["ocr_candidates"] == ["1234567890", "1234567893"]
    assert body["validation_errors"] == ["fails NPI checksum"]


def test_review_detail_exposes_versioned_decision_evidence(client, session_factory):
    task = _seed_task(
        session_factory,
        candidate_evidence=[{"engine": "rapidocr", "value": "1234567893", "confidence": .96}],
        reference_evidence=[{"source": "nppes", "value": "1234567893"}],
        registration_evidence={"confidence": .94, "method": "sift"},
        system_recommendation="1234567893",
        evidence_versions={"template": "cms1500@02-12", "routing": "1.0", "preprocessing": "1.0"},
        review_reason_codes=["OCR_DISAGREEMENT"],
    )
    body = client.get(f"/review-tasks/{task.task_id}", headers=REVIEWER_HEADERS).json()
    assert body["candidate_evidence"][0]["engine"] == "rapidocr"
    assert body["reference_evidence"][0]["source"] == "nppes"
    assert body["registration_evidence"]["confidence"] == .94
    assert body["system_recommendation"] == "1234567893"
    assert body["evidence_versions"]["routing"] == "1.0"
    assert body["review_reason_codes"] == ["OCR_DISAGREEMENT"]


def test_get_unknown_review_task_404s(client):
    response = client.get(f"/review-tasks/{uuid4()}", headers=REVIEWER_HEADERS)
    assert response.status_code == 404


def test_claim_is_atomic_and_second_reviewer_gets_conflict(client, session_factory):
    task = _seed_task(session_factory)
    first = client.post(
        f"/review-tasks/{task.task_id}/claim",
        headers=REVIEWER_HEADERS,
        json={"reviewer": "alice", "expected_version": 0},
    )
    second = client.post(
        f"/review-tasks/{task.task_id}/claim",
        headers=REVIEWER_HEADERS,
        json={"reviewer": "bob", "expected_version": 0},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "IN_PROGRESS"
    assert first.json()["version"] == 1
    assert second.status_code == 409


def test_claimed_task_can_only_be_decided_by_assignee(client, session_factory):
    task = _seed_task(session_factory)
    client.post(
        f"/review-tasks/{task.task_id}/claim",
        headers=REVIEWER_HEADERS,
        json={"reviewer": "alice", "expected_version": 0},
    )
    response = client.post(
        f"/review-tasks/{task.task_id}/correct?reviewer=bob",
        headers=REVIEWER_HEADERS,
        json={"new_value": "1396827531", "reason": "verified", "expected_version": 1},
    )
    assert response.status_code == 409


def test_decision_and_phi_safe_audit_commit_together(client, session_factory):
    task = _seed_task(session_factory)
    response = client.post(
        f"/review-tasks/{task.task_id}/correct?reviewer=alice",
        headers=REVIEWER_HEADERS,
        json={"new_value": "1396827531", "reason": "verified", "expected_version": 0},
    )
    assert response.status_code == 200
    with session_factory() as session:
        assert ReviewTaskRepository(session).audit_count(task.task_id) == 1
    audit = client.get(f"/review-tasks/{task.task_id}/audit", headers=REVIEWER_HEADERS)
    assert audit.status_code == 200
    assert audit.json()[0]["decision_hash"] is not None
    assert "1396827531" not in audit.text


def test_correct_review_task_persists_correction(client, session_factory):
    task = _seed_task(session_factory)
    _seed_extracted_field(
        session_factory,
        document_id=task.document_id,
        field_name=task.field_name,
        value="1234567890",
        field_id=task.field_id,
    )
    response = client.post(
        f"/review-tasks/{task.task_id}/correct?reviewer=alice",
        headers=REVIEWER_HEADERS,
        json={"new_value": "1396827531", "reason": "verified against original scan"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"

    with session_factory() as session:
        saved = ReviewTaskRepository(session).get(task.task_id)
    assert saved.status.value == "APPROVED"
    assert saved.correction.reviewer == "alice"
    assert saved.correction.new_value == "1396827531"
    assert saved.correction.previous_value == "1234567890"  # first OCR candidate
    assert saved.correction.reason == "verified against original scan"
    assert saved.correction.corrected_at is not None

    from apps.ingestion_api.db.models import ExtractedFieldORM, OutboxORM

    with session_factory() as session:
        field = session.get(ExtractedFieldORM, task.field_id)
        outbox = session.query(OutboxORM).one()
    assert field is not None
    assert field.normalized_value == "1396827531"
    assert field.disposition == "HUMAN_CONFIRMED"
    assert field.validation_status == "PENDING"
    assert outbox.topic == "claim.revalidation.requested"
    assert outbox.envelope["event_type"] == "claim.revalidation.requested"


def test_correcting_an_already_decided_task_returns_conflict(client, session_factory):
    task = _seed_task(session_factory)
    client.post(
        f"/review-tasks/{task.task_id}/correct?reviewer=alice",
        headers=REVIEWER_HEADERS,
        json={"new_value": "1396827531", "reason": "verified"},
    )
    response = client.post(
        f"/review-tasks/{task.task_id}/correct?reviewer=bob",
        headers=REVIEWER_HEADERS,
        json={"new_value": "1396827531", "reason": "duplicate"},
    )
    assert response.status_code == 409


def test_reject_review_task(client, session_factory):
    task = _seed_task(session_factory)
    response = client.post(
        f"/review-tasks/{task.task_id}/reject?reviewer=alice",
        headers=REVIEWER_HEADERS,
        json={"reason": "not a real claim field"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_viewer_role_cannot_correct(client, session_factory):
    task = _seed_task(session_factory)
    response = client.post(
        f"/review-tasks/{task.task_id}/correct?reviewer=alice",
        headers=VIEWER_HEADERS,
        json={"new_value": "x", "reason": "y"},
    )
    assert response.status_code == 403


# --- server-rendered UI -----------------------------------------------------------------


def test_ui_list_renders_html_table(client, session_factory):
    _seed_task(session_factory)
    response = client.get("/ui/review-tasks")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "provider_npi" in response.text


def test_ui_detail_renders_crop_ocr_and_form(client, session_factory):
    task = _seed_task(session_factory)
    response = client.get(f"/ui/review-tasks/{task.task_id}")
    assert response.status_code == 200
    assert "1234567890" in response.text  # OCR candidate
    assert "fails NPI checksum" in response.text  # validation error
    assert "<form" in response.text


def test_ui_correct_form_submission_redirects_and_persists(client, session_factory):
    task = _seed_task(session_factory)
    response = client.post(
        f"/ui/review-tasks/{task.task_id}/correct",
        data={"reviewer": "alice", "new_value": "1396827531", "reason": "checked original scan"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/review-tasks"

    with session_factory() as session:
        saved = ReviewTaskRepository(session).get(task.task_id)
    assert saved.status.value == "APPROVED"
    assert saved.correction.new_value == "1396827531"


def test_ui_detail_escapes_untrusted_values_to_avoid_xss(client, session_factory):
    task = _seed_task(
        session_factory,
        ocr_candidates=["<script>alert(1)</script>"],
        validation_errors=["<img src=x onerror=alert(1)>"],
    )
    response = client.get(f"/ui/review-tasks/{task.task_id}")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "<img src=x onerror=alert(1)>" not in response.text


# --- service layer -----------------------------------------------------------------


def test_service_rejects_correcting_a_non_open_task():
    task = ReviewTask(
        claim_id=uuid4(),
        document_id=uuid4(),
        field_id=uuid4(),
        field_name="x",
        page_number=1,
    )
    decided = task.model_copy(update={"status": ReviewTaskStatus.REJECTED})
    with pytest.raises(ReviewTaskNotOpenError):
        ReviewService().submit_correction(decided, "alice", "y", "z", "tenant-1")


# --- patient-name resolution (cross-service raw SQL lookup) --------------------


def test_list_review_tasks_resolves_correct_patient_name(client, session_factory):
    task_a = _seed_task(session_factory, field_name="patient_name")
    task_b = _seed_task(session_factory, field_name="total_charge")
    _seed_extracted_field(
        session_factory, document_id=task_a.document_id, field_name="patient_name", value="Smith, Alice"
    )
    _seed_extracted_field(
        session_factory, document_id=task_b.document_id, field_name="patient_name", value="Brown, Robert"
    )

    response = client.get("/review-tasks", headers={"X-User-Role": "reviewer"})
    assert response.status_code == 200
    by_task_id = {row["task_id"]: row for row in response.json()}

    # Each task must show its OWN document's patient -- never the other one.
    assert by_task_id[str(task_a.task_id)]["patient_name"] == "Smith, Alice"
    assert by_task_id[str(task_b.task_id)]["patient_name"] == "Brown, Robert"


def test_get_review_task_resolves_patient_first_last_fallback(client, session_factory):
    task = _seed_task(session_factory, field_name="provider_npi")
    _seed_extracted_field(
        session_factory, document_id=task.document_id, field_name="patient_last", value="Davis"
    )
    _seed_extracted_field(
        session_factory, document_id=task.document_id, field_name="patient_first", value="Michael"
    )

    response = client.get(f"/review-tasks/{task.task_id}", headers={"X-User-Role": "reviewer"})
    assert response.status_code == 200
    assert response.json()["patient_name"] == "Davis, Michael"


def test_missing_patient_name_never_leaks_another_documents_name(client, session_factory):
    task_no_name = _seed_task(session_factory, field_name="total_charge")
    task_with_name = _seed_task(session_factory, field_name="patient_name")
    _seed_extracted_field(
        session_factory, document_id=task_with_name.document_id, field_name="patient_name", value="Only, ThisOne"
    )

    response = client.get("/review-tasks", headers={"X-User-Role": "reviewer"})
    by_task_id = {row["task_id"]: row for row in response.json()}

    assert by_task_id[str(task_no_name.task_id)]["patient_name"] is None
    assert by_task_id[str(task_with_name.task_id)]["patient_name"] == "Only, ThisOne"
