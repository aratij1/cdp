"""Reference-driven revalidation test on a copy; never an actual human review."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy import select

from apps.human_review_api.db.models import ReviewTaskORM
from apps.human_review_api.main import correct_review_task
from apps.human_review_api.schemas import CorrectionRequest
from apps.ingestion_api.db.models import ExtractedFieldORM, OutboxORM
from apps.ingestion_api.db.repository import PollingOutboxRepository
from apps.ingestion_api.db.session import make_session_factory
from evaluation.governed_30_execution import LocalEngineeringObjectStore, publish
from packages.events.bus import EventBus, InMemoryEventBus
from packages.settings import Settings
from packages.storage.object_store import ObjectStore
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from workers.output_generation.consumer import OutputGenerationWorker
from workers.validation.consumer import ValidationWorker

ROOT = Path(__file__).resolve().parents[1]


async def run(root: Path = ROOT) -> dict:
    source = root / "evaluation_results/governed_30_execution"
    target = source / "revalidation_test"
    snapshot = source / "raw_execution.local.json"
    before = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    raw = json.loads(snapshot.read_text())
    reference = json.loads(
        (
            root / "evaluation_results/qualification_closure/governed_30_reference.local.json"
        ).read_text()
    )
    if raw["cohort_hash"] != reference["cohort_hash"] or any(
        c.get("actual_human_intervention") for c in raw["claims"]
    ):
        raise ValueError("RAW_REFERENCE_SCOPE_INVALID")
    if not all(
        any(e["topic"] == "extraction.completed" for e in c["events"])
        or any(e["topic"] == "page.selected"
               and e["envelope"]["payload"].get("needs_review") is True
               and "NO_AUTOMATED_EXTRACTION_ROUTE" in e["envelope"]["payload"].get("reason_codes", [])
               for e in c["events"])
        for c in raw["claims"]
    ):
        raise ValueError("RAW_EXTRACTION_NOT_COMPLETE")
    if target.exists():
        raise ValueError("REVALIDATION_TEST_ALREADY_EXISTS")
    target.mkdir()
    with (
        sqlite3.connect(
            (source / "execution.local.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
        ) as source_db,
        sqlite3.connect(target / "revalidation.local.sqlite3") as copy_db,
    ):
        source_db.backup(copy_db)
    factory = make_session_factory(
        "sqlite:///" + (target / "revalidation.local.sqlite3").resolve().as_posix()
    )
    with factory() as session:
        original_events = set(session.scalars(select(OutboxORM.outbox_id)).all())
    settings = Settings(correction_memory_path=str(target / "reference_injection.local.jsonl"))
    references = {c["claim_alias"]: c["fields"] for c in reference["claims"]}
    injected, rejected, pending = [], [], 0
    # One eligible actual task per claim is sufficient to exercise the canonical chain.
    for claim in raw["claims"]:
        for task in claim["tasks"]:
            field = references[claim["claim_alias"]].get(task["field_name"], {})
            if field.get("status") != "REFERENCE_AVAILABLE" or task["status"] != "OPEN":
                continue
            try:
                correct_review_task(
                    UUID(task["task_id"]),
                    CorrectionRequest(
                        new_value=str(field["value"]),
                        reason="REVALIDATION_TEST_REFERENCE_INJECTION_NOT_HUMAN_REVIEW",
                        expected_version=task["version"],
                    ),
                    reviewer="REVALIDATION_TEST",
                    session_factory=factory,
                    settings=settings,
                    _role="REVALIDATION_TEST",
                )
                with factory() as session:
                    corrected = session.get(ExtractedFieldORM, UUID(task["field_id"]))
                    assert corrected is not None
                    pending += (
                        corrected.disposition == "HUMAN_CONFIRMED"
                        and corrected.validation_status == "PENDING"
                    )
                injected.append(
                    {"claim_alias": claim["claim_alias"], "field_name": task["field_name"]}
                )
                break
            except Exception as exc:  # noqa: BLE001 - retain observed pipeline failures in the test report
                rejected.append(type(exc).__name__)
    bus = cast(EventBus, InMemoryEventBus())
    registry = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    validation = ValidationWorker(bus, factory, settings.pipeline_version, registry)
    output = OutputGenerationWorker(
        bus,
        cast(ObjectStore, LocalEngineeringObjectStore(source / "objects")),
        factory,
        settings.pipeline_version,
        settings.object_store_bucket,
        registry,
    )
    repo = PollingOutboxRepository(factory)
    seen = set(original_events)
    dispatched: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    while True:
        events = [e for e in await repo.get_unpublished(10000) if e.outbox_id not in seen]
        if not events:
            break
        for event in events:
            seen.add(event.outbox_id)
            try:
                if event.topic == "claim.revalidation.requested":
                    await validation.handle_one(event.envelope)
                elif event.topic == "claim.validated":
                    await output.handle_one(event.envelope)
                dispatched[event.topic] += 1
                await repo.mark_published(event.outbox_id)
            except Exception as exc:  # noqa: BLE001 - retain observed pipeline failures in the test report
                failures[f"{event.topic}:{type(exc).__name__}"] += 1
                await repo.mark_failed(event.outbox_id, type(exc).__name__)
    with factory() as session:
        persisted_events = session.scalars(select(OutboxORM)).all()
        new_events = [e for e in persisted_events if e.outbox_id not in original_events]
        decisions = [
            e.envelope["payload"].get("claim_decision", {})
            for e in new_events
            if e.topic == "claim.validated"
        ]
        outputs = [e for e in new_events if e.topic == "output.completed"]
        pending_after = session.scalars(
            select(ExtractedFieldORM).where(ExtractedFieldORM.validation_status == "PENDING")
        ).all()
        actual_approved = session.scalars(
            select(ReviewTaskORM).where(ReviewTaskORM.correction_reviewer == "REVALIDATION_TEST")
        ).all()
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != before:
        raise ValueError("RAW_SNAPSHOT_MUTATED")
    report = {
        "scope": "REVALIDATION_TEST",
        "actual_human_hitl": 0,
        "reference_injections": len(injected),
        "test_corrections_persisted": len(actual_approved),
        "human_confirmed_and_validation_pending": pending,
        "correction_attempt_rejections": dict(Counter(rejected)),
        "transactional_revalidation_requests": sum(
            e.topic == "claim.revalidation.requested" for e in new_events
        ),
        "canonical_decisions": len(decisions),
        "decision_counts": dict(Counter(d.get("disposition") for d in decisions)),
        "validation_pending_after_worker": len(pending_after),
        "outputs_completed": len(outputs),
        "unsafe_outputs": sum(
            e.envelope["payload"].get("claim_decision", {}).get("disposition") != "STP_SAFE"
            for e in outputs
        ),
        "execution_failures": dict(failures),
        "raw_snapshot_unchanged": True,
        "raw_snapshot_sha256": before,
        "cohort_hash": raw["cohort_hash"],
        "release_truth_created": False,
        "actual_human_review_created": False,
    }
    report["safe_output_positive_path_exercised"] = bool(outputs)
    report["status"] = (
        ("REVALIDATION_COMPLETED_OUTPUT_BLOCKED" if failures else "PASS")
        if injected
        and pending == len(injected)
        and len(decisions) == len(injected)
        and not report["unsafe_outputs"]
        else "INCOMPLETE"
    )
    publish(root / "evaluation_results/real_release/governed_30_revalidation_test.json", report)
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
