"""Ingestion API HTTP routes: document listing/detail and patient-name
resolution, against an in-memory SQLite DB and FakeObjectStore -- no Docker
required. Complements test_ingestion_service.py (which tests IngestionService
directly, not these FastAPI routes -- there was previously no HTTP-level
coverage of GET /documents, GET /documents/{id}, or patient-name resolution
at all)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.ingestion_api.db.models import ExtractedFieldORM
from apps.ingestion_api.db.repository import DocumentRepository
from apps.ingestion_api.db.session import make_session_factory
from apps.ingestion_api.main import app, get_object_store, get_session_factory
from packages.domain.common import ObjectRef
from packages.domain.document import Document
from packages.domain.enums import DocumentStatus, SourceFormat
from tests.conftest import FakeObjectStore


@pytest.fixture
def session_factory():
    return make_session_factory("sqlite:///:memory:")


@pytest.fixture
def object_store():
    return FakeObjectStore()


@pytest.fixture
def client(session_factory, object_store, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("OBJECT_STORE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("USE_IN_MEMORY_BUS", "true")
    monkeypatch.setenv("CORRECTION_MEMORY_PATH", str(tmp_path / "corrections.jsonl"))
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_object_store] = lambda: object_store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _seed_document(session_factory, *, status: DocumentStatus = DocumentStatus.RECEIVED) -> Document:
    document = Document(
        tenant_id="default",
        source_filename="claim.pdf",
        detected_format=SourceFormat.PDF,
        sha256=uuid4().hex + uuid4().hex,
        pipeline_version="0.1.0",
        schema_version="1.0",
        status=status,
        original_object=ObjectRef(bucket="idp-documents", key="originals/claim.pdf"),
    )
    with session_factory() as session:
        DocumentRepository(session).add(document)
        session.commit()
    return document


def _seed_extracted_field(session_factory, *, document_id, field_name, value) -> None:
    with session_factory() as session:
        session.add(
            ExtractedFieldORM(
                field_id=uuid4(),
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


def test_list_documents_returns_correct_patient_name_per_document(client, session_factory):
    doc_a = _seed_document(session_factory)
    doc_b = _seed_document(session_factory)
    _seed_extracted_field(session_factory, document_id=doc_a.document_id, field_name="patient_name", value="Smith, Alice")
    _seed_extracted_field(session_factory, document_id=doc_b.document_id, field_name="patient_name", value="Brown, Robert")

    response = client.get("/documents")
    assert response.status_code == 200
    by_id = {row["document_id"]: row for row in response.json()}

    assert by_id[str(doc_a.document_id)]["patient_name"] == "Smith, Alice"
    assert by_id[str(doc_b.document_id)]["patient_name"] == "Brown, Robert"


def test_get_document_resolves_patient_first_last_fallback(client, session_factory):
    doc = _seed_document(session_factory)
    _seed_extracted_field(session_factory, document_id=doc.document_id, field_name="patient_last", value="Davis")
    _seed_extracted_field(session_factory, document_id=doc.document_id, field_name="patient_first", value="Michael")

    response = client.get(f"/documents/{doc.document_id}")
    assert response.status_code == 200
    assert response.json()["patient_name"] == "Davis, Michael"


def test_get_document_with_no_extracted_fields_has_null_patient_name(client, session_factory):
    doc = _seed_document(session_factory)

    response = client.get(f"/documents/{doc.document_id}")
    assert response.status_code == 200
    assert response.json()["patient_name"] is None


def test_get_unknown_document_404s(client):
    response = client.get(f"/documents/{uuid4()}")
    assert response.status_code == 404


def test_list_documents_respects_tenant_filter(client, session_factory):
    _seed_document(session_factory)
    response = client.get("/documents", params={"tenant_id": "other-tenant"})
    assert response.status_code == 200
    assert response.json() == []
