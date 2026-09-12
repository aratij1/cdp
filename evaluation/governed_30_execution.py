"""Real production workers on isolated engineering storage, with no reference inputs.

The transport is in-process; durable domain changes and outbox records use the
existing repositories. This is engineering execution, never deployment evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy import select

from apps.human_review_api.consumer import HumanReviewTaskWorker
from apps.human_review_api.db.models import Base as ReviewBase
from apps.human_review_api.db.models import ReviewTaskORM
from apps.ingestion_api.db.models import DocumentORM, ExtractedFieldORM, OutboxORM, PageORM
from apps.ingestion_api.db.repository import (
    AuditRepository,
    DocumentRepository,
    PollingOutboxRepository,
    SqlAlchemyOutboxRepository,
)
from apps.ingestion_api.db.session import make_session_factory
from apps.ingestion_api.service import IngestionService
from packages.domain.common import ObjectRef, TenantContext
from packages.domain.enums import ClaimFormType
from packages.events.bus import EventBus, InMemoryEventBus
from packages.events.topics import Topic
from packages.page_observation import PageObservationService
from packages.page_observation.service import FullPageExtractor
from packages.security.malware_scan import NoOpMalwareScanner
from packages.settings import get_settings
from packages.storage.object_store import ObjectStore
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.cascade.instrumented_text_extractor import (
    CachedInstrumentedTextExtractor,
    JsonlOCRAuditSink,
)
from workers.cascade.tesseract_adapter import TesseractTextExtractor
from workers.document_preparation.consumer import DocumentPreparationWorker
from workers.output_generation.consumer import OutputGenerationWorker
from workers.page_detection.consumer import PageDetectionWorker
from workers.page_detection.router import PageRoutingService
from workers.page_detection.text_extraction import (
    PaddleOCRTextExtractor,
    RapidOCRFullPageTextExtractor,
    RapidOCRTextExtractor,
)
from workers.retry.consumer import RetryWorker
from workers.standard_form_extraction.consumer import StandardFormExtractionWorker
from workers.standard_form_extraction.extractor import StandardFormExtractionService
from workers.unstructured_extraction.consumer import UnstructuredExtractionWorker
from workers.validation.consumer import ValidationWorker

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation_results/governed_30_execution"


def publish(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temp.replace(path)


class LocalEngineeringObjectStore:
    """Content-checked local implementation of the production object-store interface."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        path = (self.root / bucket / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("OBJECT_PATH_ESCAPE")
        return path

    def put_immutable(self, bucket, key, data, content_type="application/octet-stream"):
        path = self._path(bucket, key)
        if path.exists() and path.read_bytes() != data:
            raise ValueError("IMMUTABLE_OBJECT_CHANGED")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return ObjectRef(
            bucket=bucket,
            key=key,
            content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )

    def get_bytes(self, ref):
        data = self._path(ref.bucket, ref.key).read_bytes()
        if ref.sha256 and hashlib.sha256(data).hexdigest() != ref.sha256:
            raise ValueError("OBJECT_HASH_CHANGED")
        return data

    def exists(self, bucket, key):
        return self._path(bucket, key).exists()


def row_dict(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def capture(factory, document_id: UUID, source: dict, elapsed: float, failures: list) -> dict:
    with factory() as session:
        doc = session.get(DocumentORM, document_id)
        fields = session.scalars(
            select(ExtractedFieldORM).where(ExtractedFieldORM.document_id == document_id)
        ).all()
        pages = session.scalars(select(PageORM).where(PageORM.document_id == document_id)).all()
        tasks = session.scalars(
            select(ReviewTaskORM).where(ReviewTaskORM.document_id == document_id)
        ).all()
        events = session.scalars(
            select(OutboxORM)
            .where(OutboxORM.partition_key == str(document_id))
            .order_by(OutboxORM.created_at, OutboxORM.outbox_id)
        ).all()
        validated = [e for e in events if e.topic == Topic.CLAIM_VALIDATED.value]
        outputs = [e for e in events if e.topic == Topic.OUTPUT_COMPLETED.value]
        decision = validated[-1].envelope["payload"].get("claim_decision", {}) if validated else {}
        return {
            "claim_alias": source["claim_alias"],
            "source_sha256": source["source_sha256"],
            "document_id": str(document_id),
            "document_status": doc.status,
            "source_frames": source["frames"],
            "prepared_frames": len(pages),
            "fields": [row_dict(f) for f in fields],
            "pages": [row_dict(p) for p in pages],
            "tasks": [row_dict(t) for t in tasks],
            "events": [row_dict(e) for e in events],
            "claim_decision": decision,
            "output_completed": bool(outputs) and doc.status == "OUTPUT_GENERATED",
            "actual_human_intervention": False,
            "elapsed_seconds": elapsed,
            "execution_complete": len(pages) == source["frames"]
            and bool(validated)
            and not failures,
            "failures": failures,
        }


def validate_execution_cohort(inputs: dict, manifest: dict) -> None:
    from evaluation.governed_30_reference import seal

    if manifest.get("cohort_hash") != seal(
        {k: v for k, v in manifest.items() if k != "cohort_hash"}
    ):
        raise ValueError("EXECUTION_COHORT_MANIFEST_SEAL_MISMATCH")
    expected = {c["claim_alias"]: c["source_hash"] for c in manifest["claims"]}
    supplied = {c["claim_alias"]: c["source_sha256"] for c in inputs["claims"]}
    if (
        inputs.get("cohort_hash") != manifest["cohort_hash"]
        or len(expected) != len(manifest["claims"])
        or len(supplied) != len(inputs["claims"])
        or supplied != expected
    ):
        raise ValueError("EXECUTION_COHORT_MISMATCH")


async def run(root: Path = ROOT, out: Path = OUT, *, cohort_root: Path | None = None) -> dict:
    input_path = out / "execution_input.local.json"
    inputs = json.loads(input_path.read_text())
    frozen = inputs["candidate_commit_sha"]
    from evaluation.two_track_isolation import _build as check_isolation
    from evaluation.two_track_isolation import assert_disjoint

    allowed = {"claim_alias", "source_path", "source_sha256", "frames"}
    if any(set(c) != allowed for c in inputs["claims"]):
        raise ValueError("REFERENCE_DATA_IN_EXECUTION_INPUT")
    data_root = cohort_root or root
    manifest = json.loads(
        (data_root / "evaluation_results/real_release/governed_30_manifest.json").read_text()
    )
    validate_execution_cohort(inputs, manifest)
    assert_disjoint(await asyncio.to_thread(check_isolation, data_root))
    receipt_path = out / "execution_contract.local.json"
    contract = {"candidate_commit_sha": frozen, "cohort_hash": inputs["cohort_hash"]}
    if receipt_path.exists() and json.loads(receipt_path.read_text()) != contract:
        raise ValueError("EXECUTION_RESUME_CONTRACT_MISMATCH")
    publish(receipt_path, contract)
    await asyncio.to_thread(
        subprocess.run,
        [
            "git",
            "diff",
            "--exit-code",
            frozen,
            "--",
            "workers",
            "packages",
            "config",
            "templates",
            "apps/ingestion_api",
            "apps/human_review_api",
        ],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    settings = get_settings()
    store = cast(ObjectStore, LocalEngineeringObjectStore(out / "objects"))
    factory = make_session_factory(
        "sqlite:///" + str((out / "execution.local.sqlite3").resolve()).replace("\\", "/")
    )
    ReviewBase.metadata.create_all(factory.kw["bind"])
    bus = cast(EventBus, InMemoryEventBus())
    registry = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    cms, ub = (
        registry.latest_for_form_type(f) for f in [ClaimFormType.CMS1500, ClaimFormType.UB04]
    )
    audit = JsonlOCRAuditSink(out / "ocr_audit.local.jsonl")
    router = PageRoutingService(
        cms_template=cms,
        ub_template=ub,
        text_extractor=CachedInstrumentedTextExtractor(
            TesseractTextExtractor(psm=11), audit_sink=audit
        ),
        cms_reference_image=registry.load_reference_image(cms),
        ub_reference_image=registry.load_reference_image(ub),
        enable_router_v3=settings.enable_router_v3,
    )
    standard = StandardFormExtractionWorker(
        bus,
        store,
        factory,
        settings.pipeline_version,
        registry,
        StandardFormExtractionService(
            CachedInstrumentedTextExtractor(RapidOCRTextExtractor(), audit_sink=audit)
        ),
        PageObservationService(
            cast(
                FullPageExtractor,
                CachedInstrumentedTextExtractor(RapidOCRFullPageTextExtractor(), audit_sink=audit),
            ),
            preprocessing_version="document-preparation-v1",
        ),
    )
    workers: dict = {
        Topic.DOCUMENT_RECEIVED.value: DocumentPreparationWorker(
            bus, store, settings.object_store_bucket, factory, settings.pipeline_version
        ),
        Topic.DOCUMENT_PREPARED.value: PageDetectionWorker(
            bus, store, factory, settings.pipeline_version, router
        ),
        Topic.EXTRACTION_STANDARD_REQUESTED.value: standard,
        Topic.EXTRACTION_UNSTRUCTURED_REQUESTED.value: UnstructuredExtractionWorker(
            bus,
            store,
            factory,
            settings.pipeline_version,
            CachedInstrumentedTextExtractor(PaddleOCRTextExtractor(), audit_sink=audit),
        ),
        Topic.EXTRACTION_COMPLETED.value: ValidationWorker(
            bus, factory, settings.pipeline_version, registry
        ),
        Topic.FIELD_RETRY_REQUESTED.value: RetryWorker(
            bus, store, factory, settings.pipeline_version, vlm_enabled=settings.vlm_enabled
        ),
        Topic.HUMAN_REVIEW_REQUESTED.value: HumanReviewTaskWorker(bus, factory),
        Topic.CLAIM_VALIDATED.value: OutputGenerationWorker(
            bus, store, factory, settings.pipeline_version, settings.object_store_bucket, registry
        ),
    }
    workers[Topic.CLAIM_REVALIDATION_REQUESTED.value] = workers[Topic.EXTRACTION_COMPLETED.value]
    repository = PollingOutboxRepository(factory)
    completed = []
    for source in inputs["claims"]:
        snapshot_path = out / (source["claim_alias"] + ".raw.local.json")
        if snapshot_path.exists():
            previous = json.loads(snapshot_path.read_text())
            if previous["execution_complete"]:
                completed.append(previous)
                continue
            archive = out / "incomplete_attempts"
            archive.mkdir(exist_ok=True)
            retained = archive / (str(time.time_ns()) + "_" + snapshot_path.name)
            snapshot_path.rename(retained)
        data = Path(source["source_path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != source["source_sha256"]:
            raise ValueError("SOURCE_HASH_CHANGED")
        started = time.perf_counter()
        with factory() as session:
            ingestion = IngestionService(
                store,
                settings.object_store_bucket,
                DocumentRepository(session),
                AuditRepository(session),
                SqlAlchemyOutboxRepository(session),
                NoOpMalwareScanner(),
                settings.pipeline_version,
                settings.schema_version,
                settings.max_upload_size_bytes,
            )
            ingested = await ingestion.ingest(
                source["claim_alias"] + ".tiff",
                data,
                TenantContext(tenant_id="governed-30-engineering"),
            )
            session.commit()
            document_id = ingested.document.document_id
        failures = []
        seen = set()
        while True:
            events = [
                e
                for e in await repository.get_unpublished(10000)
                if e.envelope.document_id == document_id and e.outbox_id not in seen
            ]
            if not events:
                break
            for event in events:
                seen.add(event.outbox_id)
                worker = workers.get(event.topic)
                print(
                    json.dumps({"claim": source["claim_alias"], "topic": event.topic}), flush=True
                )
                try:
                    if worker:
                        await worker.handle_one(event.envelope)
                    elif event.topic in {
                        Topic.HANDWRITING_EXTRACTION_REQUESTED.value,
                        Topic.VLM_REQUESTED.value,
                        Topic.PROCESSING_DLQ.value,
                    }:
                        raise RuntimeError("UNAVAILABLE_REQUIRED_CONSUMER")
                    await repository.mark_published(event.outbox_id)
                except Exception as exc:
                    failures.append({"topic": event.topic, "error_type": type(exc).__name__})
                    logging.getLogger(__name__).exception(
                        "Engineering event failed; details remain in local log"
                    )
                    await repository.mark_failed(event.outbox_id, type(exc).__name__)
        captured = capture(factory, document_id, source, time.perf_counter() - started, failures)
        publish(snapshot_path, captured)
        completed.append(captured)
        publish(
            out / "progress.json",
            {
                "claims_attempted": len(completed),
                "claims_total": len(inputs["claims"]),
                "claims_execution_complete": sum(c["execution_complete"] for c in completed),
                "reference_values_used": False,
            },
        )
    result = {
        "scope": "GOVERNED_ENGINEERING",
        "authority": "ENGINEERING_REFERENCE_ONLY",
        "candidate_commit_sha": frozen,
        "cohort_hash": inputs["cohort_hash"],
        "runtime": "PRODUCTION_WORKERS_LOCAL_SQLITE_OBJECT_STORE_IN_PROCESS_TRANSPORT",
        "reference_values_used_for_inference": False,
        "actual_human_reviews": 0,
        "claims": completed,
    }
    publish(out / "raw_execution.local.json", result)
    return result


if __name__ == "__main__":
    logging.basicConfig(filename=str(OUT / "execution_errors.local.log"), level=logging.WARNING)
    asyncio.run(run())
