"""Human review API + minimal server-rendered UI: review only failed
fields, never a whole claim. Every correction/rejection persists reviewer,
timestamp, previous value, new value, and reason (`FieldCorrection`), and
emits an immutable `AuditEvent`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from apps.human_review_api.db.repository import (
    ConcurrentReviewUpdateError,
    ReviewTaskRepository,
)
from apps.human_review_api.db.session import make_session_factory
from apps.human_review_api.html import render_task_detail, render_task_list
from apps.human_review_api.schemas import (
    ClaimRequest,
    CorrectionPromotionCandidate,
    CorrectionRequest,
    RejectionRequest,
    ReviewAuditSummary,
    ReviewTaskDetail,
    ReviewTaskSummary,
)
from apps.human_review_api.service import (
    InvalidCorrectionError,
    ReviewService,
    ReviewTaskNotOpenError,
)
from apps.ingestion_api.db.models import ExtractedFieldORM
from apps.ingestion_api.db.repository import SqlAlchemyOutboxRepository
from packages.deterministic_field_tuning import validate_field
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.observability import REGISTRY, configure_logging
from packages.observability.metrics import human_review_total
from packages.retraining import CorrectionMemory
from packages.security.fastapi_rbac import require_permission
from packages.security.rbac import Permission
from packages.settings import Settings, get_settings
from packages.storage.object_store import ObjectRef, ObjectStore, ObjectStoreSettings

_state: dict[str, object] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("human-review-api")
    settings = get_settings()
    _state["settings"] = settings
    _state["session_factory"] = make_session_factory(settings.database_url)
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


app = FastAPI(title="IDP Human Review API", version="0.1.0", lifespan=lifespan)


def get_session_factory() -> sessionmaker[Session]:
    return _state["session_factory"]  # type: ignore[return-value]


def get_object_store() -> ObjectStore:
    return _state["object_store"]  # type: ignore[return-value]


def get_settings_dep() -> Settings:
    return _state["settings"]  # type: ignore[return-value]


def _review_service(settings: Settings) -> ReviewService:
    def correction_validator(field_name: str, value: str) -> bool:
        if not value.strip():
            return False
        result = validate_field(field_name, value)
        return result.valid or result.evidence == "NO_DETERMINISTIC_RULE"

    from packages.retraining import JsonlCorrectionSink
    sink = JsonlCorrectionSink(Path(settings.correction_memory_path))
    return ReviewService(validator=correction_validator, correction_sink=sink)


def _queue_revalidation(session: Session, task, corrected_value: str) -> None:
    field = session.get(ExtractedFieldORM, task.field_id)
    if field is not None:
        field.raw_value = corrected_value
        field.normalized_value = corrected_value
        field.confidence = 1.0
        field.validation_status = "PENDING"
        field.validation_reasons = []
        field.disposition = "HUMAN_CONFIRMED"

    envelope = EventEnvelope(
        event_type=Topic.CLAIM_REVALIDATION_REQUESTED.value,
        correlation_id=task.claim_id,
        document_id=task.document_id,
        claim_id=task.claim_id,
        pipeline_version=get_settings().pipeline_version,
        payload={
            "document_id": str(task.document_id),
            "claim_id": str(task.claim_id),
            "field_id": str(task.field_id),
            "field_name": task.field_name,
            "correction_reviewer": task.correction.reviewer if task.correction else None,
        },
    )
    SqlAlchemyOutboxRepository(session).add_sync(
        OutboxRecord(
            topic=Topic.CLAIM_REVALIDATION_REQUESTED.value,
            envelope=envelope,
            partition_key=str(task.document_id),
        )
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if "session_factory" not in _state:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def _signed_url(object_store: ObjectStore, ref: dict | None) -> str | None:
    if ref is None:
        return None
    return object_store.signed_get_url(ObjectRef.model_validate(ref))


def _resolve_patient_names(session: Session, document_ids: set[UUID]) -> dict[UUID, str]:
    """Look up each document's patient name via a raw SQL SELECT against
    `extracted_fields` (owned by apps.ingestion_api) -- deliberately not an
    ORM import of ExtractedFieldORM, so this service stays decoupled from
    ingestion_api's schema module.

    The bind parameter is typed as sqlalchemy.types.Uuid so SQLAlchemy's
    dialect-aware bind processor serializes it correctly for whichever
    backend is in play: hex-no-dash CHAR(32) on SQLite (what
    Mapped[uuid.UUID] columns actually store there -- confirmed by
    inspection), native uuid on PostgreSQL. Passing a bare Python UUID
    object into a raw text() query without this type annotation does NOT
    work on SQLite (the driver rejects it outright) and does not reliably
    match PostgreSQL's uuid columns either -- always use this helper rather
    than reintroducing an ad hoc text() query with un-typed bind params.

    A document with no readable patient/first/last field returns no entry
    in the result dict (never a wrong or borrowed name) -- callers should
    treat a missing key as "unknown", not fall back to any other document's
    value.
    """
    if not document_ids:
        return {}

    from sqlalchemy import bindparam, text
    from sqlalchemy.types import Uuid as SAUuid

    stmt = text(
        """
        SELECT document_id, field_name, raw_value, normalized_value
        FROM extracted_fields
        WHERE document_id IN :doc_ids
          AND field_name IN ('patient_name', 'patient_last', 'patient_first')
        """
    ).bindparams(bindparam("doc_ids", expanding=True, type_=SAUuid()))

    try:
        rows = session.execute(stmt, {"doc_ids": list(document_ids)}).all()
    except Exception:
        logging.getLogger(__name__).exception(
            "patient-name lookup failed for documents %s", document_ids
        )
        return {}

    patient_names: dict[UUID, str] = {}
    first_names: dict[UUID, str] = {}
    last_names: dict[UUID, str] = {}
    for doc_id_raw, fname, raw_val, norm_val in rows:
        doc_id = doc_id_raw if isinstance(doc_id_raw, UUID) else UUID(str(doc_id_raw))
        value = norm_val or raw_val
        if not value:
            continue
        if fname == "patient_name":
            patient_names[doc_id] = value
        elif fname == "patient_last":
            last_names[doc_id] = value
        elif fname == "patient_first":
            first_names[doc_id] = value

    for doc_id in document_ids:
        if doc_id in patient_names:
            continue
        last = last_names.get(doc_id, "")
        first = first_names.get(doc_id, "")
        if last and first:
            patient_names[doc_id] = f"{last}, {first}"
        elif last or first:
            patient_names[doc_id] = last or first

    return patient_names


# --- JSON API -----------------------------------------------------------------


@app.get("/review-tasks", response_model=list[ReviewTaskSummary])
def list_review_tasks(
    status: str = "open",
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    _role=Depends(require_permission(Permission.REVIEW_FIELD)),
) -> list[ReviewTaskSummary]:
    with session_factory() as session:
        repo = ReviewTaskRepository(session)
        if status == "all":
            tasks = repo.list_all()
        elif status == "open":
            tasks = repo.list_open()
        else:
            statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
            tasks = repo.list_by_status(statuses)
        
        patient_names = _resolve_patient_names(session, {t.document_id for t in tasks})

    return [ReviewTaskSummary.from_domain(t, patient_names.get(t.document_id)) for t in tasks]


@app.get("/correction-promotion-candidates", response_model=list[CorrectionPromotionCandidate])
def list_correction_promotion_candidates(
    settings: Settings = Depends(get_settings_dep),
    _role=Depends(require_permission(Permission.REVIEW_FIELD)),
) -> list[CorrectionPromotionCandidate]:
    patterns = CorrectionMemory(Path(settings.correction_memory_path)).promotion_candidates(
        settings.default_tenant_id,
    )
    return [
        CorrectionPromotionCandidate.model_validate(pattern, from_attributes=True)
        for pattern in patterns
    ]


@app.get("/review-tasks/{task_id}", response_model=ReviewTaskDetail)
def get_review_task(
    task_id: UUID,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    object_store: ObjectStore = Depends(get_object_store),
    _role=Depends(require_permission(Permission.REVIEW_FIELD)),
) -> ReviewTaskDetail:
    with session_factory() as session:
        task = ReviewTaskRepository(session).get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="review task not found")

        patient_name = _resolve_patient_names(session, {task.document_id}).get(task.document_id)

    return ReviewTaskDetail.from_domain(
        task,
        crop_signed_url=_signed_url(object_store, task.crop_object),
        page_context_signed_url=_signed_url(object_store, task.page_context_object),
        patient_name=patient_name,
    )


@app.post("/review-tasks/{task_id}/claim", response_model=ReviewTaskSummary)
def claim_review_task(
    task_id: UUID,
    body: ClaimRequest,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    _role=Depends(require_permission(Permission.REVIEW_FIELD)),
) -> ReviewTaskSummary:
    with session_factory() as session:
        repo = ReviewTaskRepository(session)
        task = repo.claim(task_id, body.reviewer, body.expected_version)
        if task is None:
            raise HTTPException(status_code=409, detail="task already claimed or version changed")
        repo.append_audit(task, "TASK_CLAIMED", f"user:{body.reviewer}", "CLAIMED")
        session.commit()
    return ReviewTaskSummary.from_domain(task)


@app.get("/review-tasks/{task_id}/audit", response_model=list[ReviewAuditSummary])
def get_review_audit(
    task_id: UUID,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    _role=Depends(require_permission(Permission.REVIEW_FIELD)),
) -> list[ReviewAuditSummary]:
    with session_factory() as session:
        rows = ReviewTaskRepository(session).list_audit(task_id)
    return [ReviewAuditSummary.model_validate(row, from_attributes=True) for row in rows]


@app.post("/review-tasks/{task_id}/correct", response_model=ReviewTaskSummary)
def correct_review_task(
    task_id: UUID,
    body: CorrectionRequest,
    reviewer: str = "anonymous",
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings_dep),
    _role=Depends(require_permission(Permission.CORRECT_FIELD)),
) -> ReviewTaskSummary:
    with session_factory() as session:
        repo = ReviewTaskRepository(session)
        task = repo.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="review task not found")
        try:
            decision = _review_service(settings).submit_correction(
                task, reviewer, body.new_value, body.reason, settings.default_tenant_id
            )
        except ReviewTaskNotOpenError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except InvalidCorrectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            saved = repo.save(decision.task, body.expected_version)
        except ConcurrentReviewUpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        repo.append_audit(
            saved,
            "FIELD_CORRECTED",
            f"user:{reviewer}",
            "DETERMINISTIC_VALIDATION_PASSED",
            body.new_value,
        )
        _queue_revalidation(session, saved, body.new_value)
        session.commit()
    human_review_total.labels(reason="corrected").inc()
    return ReviewTaskSummary.from_domain(saved)


@app.post("/review-tasks/{task_id}/reject", response_model=ReviewTaskSummary)
def reject_review_task(
    task_id: UUID,
    body: RejectionRequest,
    reviewer: str = "anonymous",
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings_dep),
    _role=Depends(require_permission(Permission.CORRECT_FIELD)),
) -> ReviewTaskSummary:
    with session_factory() as session:
        repo = ReviewTaskRepository(session)
        task = repo.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="review task not found")
        try:
            decision = ReviewService().submit_rejection(
                task, reviewer, body.reason, settings.default_tenant_id
            )
        except ReviewTaskNotOpenError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            saved = repo.save(decision.task, body.expected_version)
        except ConcurrentReviewUpdateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        repo.append_audit(saved, "FIELD_REJECTED", f"user:{reviewer}", "REVIEWER_REJECTED")
        session.commit()
    human_review_total.labels(reason="rejected").inc()
    return ReviewTaskSummary.from_domain(saved)


# --- server-rendered UI -----------------------------------------------------------------


@app.get("/ui/review-tasks", response_class=HTMLResponse)
def ui_list_review_tasks(
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> str:
    with session_factory() as session:
        tasks = ReviewTaskRepository(session).list_open()
    return render_task_list([ReviewTaskSummary.from_domain(t) for t in tasks])


@app.get("/ui/review-tasks/{task_id}", response_class=HTMLResponse)
def ui_get_review_task(
    task_id: UUID,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    object_store: ObjectStore = Depends(get_object_store),
) -> str:
    with session_factory() as session:
        task = ReviewTaskRepository(session).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="review task not found")
    detail = ReviewTaskDetail.from_domain(
        task,
        crop_signed_url=_signed_url(object_store, task.crop_object),
        page_context_signed_url=_signed_url(object_store, task.page_context_object),
    )
    return render_task_detail(detail)


@app.post("/ui/review-tasks/{task_id}/correct")
def ui_correct_review_task(
    task_id: UUID,
    reviewer: str = Form(...),
    new_value: str = Form(...),
    reason: str = Form(...),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings_dep),
):
    with session_factory() as session:
        repo = ReviewTaskRepository(session)
        task = repo.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="review task not found")
        decision = _review_service(settings).submit_correction(
            task, reviewer, new_value, reason, settings.default_tenant_id
        )
        saved = repo.save(decision.task)
        repo.append_audit(
            saved,
            "FIELD_CORRECTED",
            f"user:{reviewer}",
            "DETERMINISTIC_VALIDATION_PASSED",
            new_value,
        )
        _queue_revalidation(session, saved, new_value)
        session.commit()
    return RedirectResponse(url="/ui/review-tasks", status_code=303)


@app.post("/ui/review-tasks/{task_id}/reject")
def ui_reject_review_task(
    task_id: UUID,
    reviewer: str = Form(...),
    reason: str = Form(...),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    settings: Settings = Depends(get_settings_dep),
):
    with session_factory() as session:
        repo = ReviewTaskRepository(session)
        task = repo.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="review task not found")
        decision = ReviewService().submit_rejection(
            task, reviewer, reason, settings.default_tenant_id
        )
        saved = repo.save(decision.task)
        repo.append_audit(saved, "FIELD_REJECTED", f"user:{reviewer}", "REVIEWER_REJECTED")
        session.commit()
    return RedirectResponse(url="/ui/review-tasks", status_code=303)
