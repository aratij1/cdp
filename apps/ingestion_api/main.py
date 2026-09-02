"""Ingestion API: streaming upload with size limits, magic-byte validation,
dedup, idempotent intake. See `apps/ingestion_api/batch_ingest.py` for the
batch-directory intake path used by ops/tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from apps.ingestion_api.db.repository import (
    AuditRepository,
    DocumentRepository,
    ExtractedFieldRepository,
    PollingOutboxRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from apps.ingestion_api.schemas import (
    DocumentResponse,
    DocumentResultResponse,
    ExtractedFieldResponse,
)
from apps.ingestion_api.service import (
    FileTooLargeError,
    IngestionService,
    MalwareDetectedError,
    UnsupportedFileTypeError,
)
from packages.domain.common import TenantContext
from packages.domain.enums import DocumentStatus
from packages.events.bus import AIOKafkaEventBus, InMemoryEventBus
from packages.events.outbox import OutboxRelay
from packages.observability import REGISTRY, configure_logging
from packages.observability.metrics import cache_hits_total, documents_received_total
from packages.security.malware_scan import NoOpMalwareScanner
from packages.settings import Settings, get_settings
from packages.storage.object_store import ObjectStore, ObjectStoreSettings

_state: dict[str, object] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("ingestion-api")
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
    object_store.ensure_bucket(settings.object_store_bucket)
    _state["object_store"] = object_store

    event_bus = (
        InMemoryEventBus()
        if settings.use_in_memory_bus
        else AIOKafkaEventBus(settings.kafka_bootstrap_servers)
    )
    relay = OutboxRelay(
        repository=PollingOutboxRepository(session_factory),
        event_bus=event_bus,
    )
    relay_task = asyncio.create_task(relay.run_forever())

    yield

    relay.stop()
    await relay_task
    await event_bus.close()
    _state.clear()


app = FastAPI(title="IDP Ingestion API", version="0.1.0", lifespan=lifespan)


def get_session_factory() -> sessionmaker[Session]:
    return _state["session_factory"]  # type: ignore[return-value]


def get_object_store() -> ObjectStore:
    return _state["object_store"]  # type: ignore[return-value]


def get_settings_dep() -> Settings:
    return _state["settings"]  # type: ignore[return-value]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if "session_factory" not in _state or "object_store" not in _state:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/documents", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    tenant_id: str = "default",
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    object_store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings_dep),
) -> DocumentResponse:
    data = await file.read()

    with session_factory() as session:
        service = IngestionService(
            object_store=object_store,
            bucket=settings.object_store_bucket,
            document_repository=DocumentRepository(session),
            audit_repository=AuditRepository(session),
            outbox_repository=SqlAlchemyOutboxRepository(session),
            malware_scanner=NoOpMalwareScanner(),
            pipeline_version=settings.pipeline_version,
            schema_version=settings.schema_version,
            max_upload_size_bytes=settings.max_upload_size_bytes,
        )
        try:
            result = await service.ingest(
                filename=file.filename or "unnamed",
                data=data,
                tenant=TenantContext(tenant_id=tenant_id),
            )
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        except FileTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except MalwareDetectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.commit()

    documents_received_total.labels(
        tenant_id=tenant_id, detected_format=result.document.detected_format.value
    ).inc()
    if not result.is_new_document:
        cache_hits_total.inc()

    return DocumentResponse.from_domain(result.document, is_new=result.is_new_document)


@app.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    tenant_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> list[DocumentResponse]:
    with session_factory() as session:
        docs = DocumentRepository(session).list_all(tenant_id=tenant_id, limit=limit, offset=offset)
        doc_ids = [d.document_id for d in docs]
        patient_names: dict[UUID, str] = {}
        if doc_ids:
            from sqlalchemy import select
            from apps.ingestion_api.db.models import ExtractedFieldORM
            stmt = select(
                ExtractedFieldORM.document_id,
                ExtractedFieldORM.field_name,
                ExtractedFieldORM.raw_value,
                ExtractedFieldORM.normalized_value,
            ).where(
                ExtractedFieldORM.document_id.in_(doc_ids),
                ExtractedFieldORM.field_name.in_(["patient_name", "patient_last", "patient_first"]),
            )
            rows = session.execute(stmt).all()
            first_names: dict[UUID, str] = {}
            last_names: dict[UUID, str] = {}
            for doc_id, fname, raw_val, norm_val in rows:
                val = norm_val or raw_val
                if fname == "patient_name":
                    patient_names[doc_id] = val
                elif fname == "patient_last":
                    last_names[doc_id] = val
                elif fname == "patient_first":
                    first_names[doc_id] = val
            for doc_id in doc_ids:
                if doc_id not in patient_names:
                    last = last_names.get(doc_id, "")
                    first = first_names.get(doc_id, "")
                    if last and first:
                        patient_names[doc_id] = f"{last}, {first}"
                    elif last or first:
                        patient_names[doc_id] = last or first

        return [DocumentResponse.from_domain(d, is_new=False, patient_name=patient_names.get(d.document_id)) for d in docs]


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DocumentResponse:
    with session_factory() as session:
        document = DocumentRepository(session).get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        
        from sqlalchemy import select
        from apps.ingestion_api.db.models import ExtractedFieldORM
        stmt = select(
            ExtractedFieldORM.field_name,
            ExtractedFieldORM.raw_value,
            ExtractedFieldORM.normalized_value,
        ).where(
            ExtractedFieldORM.document_id == document_id,
            ExtractedFieldORM.field_name.in_(["patient_name", "patient_last", "patient_first"]),
        )
        rows = session.execute(stmt).all()
        patient_name: str | None = None
        first_name: str | None = None
        last_name: str | None = None
        for fname, raw_val, norm_val in rows:
            val = norm_val or raw_val
            if fname == "patient_name":
                patient_name = val
            elif fname == "patient_last":
                last_name = val
            elif fname == "patient_first":
                first_name = val
        if not patient_name:
            if last_name and first_name:
                patient_name = f"{last_name}, {first_name}"
            elif last_name or first_name:
                patient_name = last_name or first_name

    return DocumentResponse.from_domain(document, is_new=False, patient_name=patient_name)


@app.get("/documents/{document_id}/results", response_model=DocumentResultResponse)
def get_document_results(
    document_id: UUID,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> DocumentResultResponse:
    with session_factory() as session:
        document = DocumentRepository(session).get(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="document not found")
        fields = ExtractedFieldRepository(session).list_for_document(document_id)
    terminal_statuses = {
        DocumentStatus.NEEDS_REVIEW,
        DocumentStatus.COMPLETED,
        DocumentStatus.OUTPUT_GENERATED,
        DocumentStatus.FAILED,
        DocumentStatus.QUARANTINED,
    }
    return DocumentResultResponse(
        document=DocumentResponse.from_domain(document, is_new=False),
        fields=[ExtractedFieldResponse.from_domain(field) for field in fields],
        field_count=len(fields),
        # The current vertical slice stops at VALIDATING after persisted OCR.
        processing_complete=bool(fields) or document.status in terminal_statuses,
    )
