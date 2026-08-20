"""Unit tests for Output API endpoints."""


from fastapi.testclient import TestClient

from apps.ingestion_api.db.repository import DocumentRepository
from apps.ingestion_api.db.session import make_session_factory
from apps.output_api.main import app, get_db_session, get_object_store
from packages.domain.common import ObjectRef
from packages.domain.document import Document
from packages.domain.enums import DocumentStatus, SourceFormat


def _document() -> Document:
    return Document(
        tenant_id="tenant-1",
        source_filename="claim.tiff",
        detected_format=SourceFormat.TIFF,
        sha256="f" * 64,
        original_object=ObjectRef(bucket="idp-documents", key="documents/aa/bb/x.tiff"),
        pipeline_version="0.1.0",
        schema_version="1.0",
        status=DocumentStatus.OUTPUT_GENERATED,
    )


def test_output_api_endpoints(fake_object_store):
    session_factory = make_session_factory("sqlite:///:memory:")
    doc = _document()

    with session_factory() as session:
        doc_repo = DocumentRepository(session)
        doc_repo.add(doc)
        session.commit()

    # Pre-populate dummy outputs in fake_object_store
    prefix = f"outputs/{doc.tenant_id}/{doc.document_id}"
    fake_object_store.put_immutable("idp-documents", f"{prefix}/canonical_claim.json", b"{}", "application/json")
    fake_object_store.put_immutable("idp-documents", f"{prefix}/evidence_manifest.json", b"{}", "application/json")

    def _override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def _override_store():
        return fake_object_store

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_object_store] = _override_store

    client = TestClient(app)

    # Health check
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # List claims
    res = client.get("/api/v1/claims")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["tenant_id"] == "tenant-1"

    # Claim detail
    res = client.get(f"/api/v1/claims/{doc.document_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["document_id"] == str(doc.document_id)
    assert "canonical_json" in detail["available_outputs"]
    assert "evidence_manifest" in detail["available_outputs"]

    # Download output
    res = client.get(f"/api/v1/claims/{doc.document_id}/outputs/canonical_json")
    assert res.status_code == 200
    download = res.json()
    assert download["output_type"] == "canonical_json"
    assert "download_url" in download

    # Clean up overrides
    app.dependency_overrides.clear()
