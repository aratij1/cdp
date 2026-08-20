"""Output API: REST API to list claims, view processing details, and fetch
presigned download URLs for generated output artifacts.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from apps.human_review_api.db.session import make_session_factory
from apps.output_api.schemas import (
    ClaimDetailResponse,
    ClaimListResponse,
    ClaimSummary,
    OutputDownloadResponse,
)
from apps.output_api.service import OutputService
from packages.observability import REGISTRY, configure_logging
from packages.settings import get_settings
from packages.storage.object_store import ObjectStore, ObjectStoreSettings

_state: dict[str, object] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("output-api")
    settings = get_settings()
    _state["settings"] = settings
    session_factory = make_session_factory(settings.database_url)
    _state["session_factory"] = session_factory
    object_store = ObjectStore(
        ObjectStoreSettings(
            endpoint_url=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            use_ssl=settings.object_store_use_ssl,
        )
    )
    _state["object_store"] = object_store
    yield
    _state.clear()


app = FastAPI(title="IDP Output API", version="0.1.0", lifespan=lifespan)


def get_db_session():
    session_factory: sessionmaker[Session] = _state["session_factory"]  # type: ignore
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_object_store() -> ObjectStore:
    return _state["object_store"]  # type: ignore


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v1/claims", response_model=ClaimListResponse)
def list_claims(
    tenant_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db_session),
    object_store: ObjectStore = Depends(get_object_store),
):
    service = OutputService(session, object_store)
    rows, total = service.list_claims(tenant_id=tenant_id, status=status, limit=limit, offset=offset)
    items = [
        ClaimSummary(
            document_id=r.document_id,
            claim_id=r.claim_id,
            tenant_id=r.tenant_id,
            status=r.status,
            filename=r.source_filename,
            received_at=r.received_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return ClaimListResponse(items=items, total=total)


@app.get("/api/v1/claims/{claim_id}", response_model=ClaimDetailResponse)
def get_claim_detail(
    claim_id: UUID,
    session: Session = Depends(get_db_session),
    object_store: ObjectStore = Depends(get_object_store),
):
    service = OutputService(session, object_store)
    doc = service.get_claim(claim_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")

    outputs = service.get_available_outputs(doc)
    return ClaimDetailResponse(
        document_id=doc.document_id,
        claim_id=doc.claim_id,
        tenant_id=doc.tenant_id,
        status=doc.status,
        filename=doc.source_filename,
        page_count=doc.page_count,
        received_at=doc.received_at,
        updated_at=doc.updated_at,
        available_outputs=outputs,
    )


@app.get("/api/v1/claims/{claim_id}/outputs/{output_type}", response_model=OutputDownloadResponse)
def download_claim_output(
    claim_id: UUID,
    output_type: str,
    session: Session = Depends(get_db_session),
    object_store: ObjectStore = Depends(get_object_store),
):
    service = OutputService(session, object_store)
    doc = service.get_claim(claim_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")

    result = service.generate_download_url(doc, output_type)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"output type '{output_type}' not available for claim {claim_id}",
        )

    object_key, download_url = result
    return OutputDownloadResponse(
        claim_id=doc.claim_id or doc.document_id,
        output_type=output_type,
        object_uri=object_key,
        download_url=download_url,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
