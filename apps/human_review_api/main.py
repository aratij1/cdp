"""Human review API + minimal server-rendered UI: review only failed
fields, never a whole claim. Every correction/rejection persists reviewer,
timestamp, previous value, new value, and reason (`FieldCorrection`), and
emits an immutable `AuditEvent`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from apps.human_review_api.db.repository import ReviewTaskRepository
from apps.human_review_api.db.session import make_session_factory
from apps.human_review_api.html import render_task_detail, render_task_list
from apps.human_review_api.schemas import (
    CorrectionPromotionCandidate,
    CorrectionRequest,
    RejectionRequest,
    ReviewTaskDetail,
    ReviewTaskSummary,
)
from apps.human_review_api.service import (
    InvalidCorrectionError,
    ReviewService,
    ReviewTaskNotOpenError,
)
from packages.deterministic_field_tuning import validate_field
from packages.observability import REGISTRY, configure_logging
from packages.observability.metrics import human_review_total
from packages.retraining import CorrectionMemory, JsonlCorrectionSink
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

    return ReviewService(
        validator=correction_validator,
        correction_sink=JsonlCorrectionSink(Path(settings.correction_memory_path)),
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


# --- JSON API -----------------------------------------------------------------


@app.get("/review-tasks", response_model=list[ReviewTaskSummary])
def list_review_tasks(
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
    _role=Depends(require_permission(Permission.REVIEW_FIELD)),
) -> list[ReviewTaskSummary]:
    with session_factory() as session:
        tasks = ReviewTaskRepository(session).list_open()
    return [ReviewTaskSummary.from_domain(t) for t in tasks]


@app.get("/correction-promotion-candidates", response_model=list[CorrectionPromotionCandidate])
def list_correction_promotion_candidates(
    settings: Settings = Depends(get_settings_dep),
    _role=Depends(require_permission(Permission.REVIEW_FIELD)),
) -> list[CorrectionPromotionCandidate]:
    patterns = CorrectionMemory(Path(settings.correction_memory_path)).promotion_candidates(
        settings.default_tenant_id,
    )
    return [CorrectionPromotionCandidate.model_validate(pattern, from_attributes=True) for pattern in patterns]


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
    return ReviewTaskDetail.from_domain(
        task,
        crop_signed_url=_signed_url(object_store, task.crop_object),
        page_context_signed_url=_signed_url(object_store, task.page_context_object),
    )


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
        repo.save(decision.task)
        session.commit()
    human_review_total.labels(reason="corrected").inc()
    return ReviewTaskSummary.from_domain(decision.task)


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
        repo.save(decision.task)
        session.commit()
    human_review_total.labels(reason="rejected").inc()
    return ReviewTaskSummary.from_domain(decision.task)


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
        repo.save(decision.task)
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
        repo.save(decision.task)
        session.commit()
    return RedirectResponse(url="/ui/review-tasks", status_code=303)
