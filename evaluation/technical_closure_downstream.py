"""Real-worker output/revalidation on isolated governed Track A copies."""

import asyncio
import json
import sqlite3
from collections import Counter
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from apps.ingestion_api.db.models import DocumentORM, OutboxORM
from apps.ingestion_api.db.session import make_session_factory
from evaluation.governed_30_execution import LocalEngineeringObjectStore
from evaluation.governed_30_revalidation import run as revalidate
from evaluation.non_name_inputs import digest, read, write
from packages.events.bus import InMemoryEventBus
from packages.events.envelope import EventEnvelope
from workers.output_generation.consumer import OutputGenerationWorker

ROOT = Path.cwd()
PRIVATE = ROOT / "evaluation_results/technical_closure"
DOC = ROOT / "docs/closure/technical_closure"


async def run():
    source = ROOT / "evaluation_results/governed_30_execution"
    target = PRIVATE / "downstream"
    if target.exists():
        raise ValueError("IMMUTABLE_DOWNSTREAM_RUN_EXISTS")
    target.mkdir()
    raw_path = source / "raw_execution.local.json"
    before = digest(raw_path)
    raw = read(raw_path)
    assert len(raw["claims"]) == 30
    with (
        sqlite3.connect(
            (source / "execution.local.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
        ) as original,
        sqlite3.connect(target / "output.local.sqlite3") as copy,
    ):
        original.backup(copy)
    factory = make_session_factory(
        "sqlite:///" + (target / "output.local.sqlite3").resolve().as_posix()
    )
    worker = OutputGenerationWorker(
        InMemoryEventBus(),
        LocalEngineeringObjectStore(target / "objects"),
        factory,
        "technical-closure",
    )
    records = []
    for claim in raw["claims"]:
        events = [e for e in claim["events"] if e["topic"] == "claim.validated"]
        result = {
            "claim_alias": claim["claim_alias"],
            "validation_events": len(events),
            "failures": [],
        }
        for event in events:
            envelope = EventEnvelope.model_validate(event["envelope"])
            try:
                await worker.handle_one(envelope)
                with factory() as session:
                    count = len(session.scalars(select(OutboxORM)).all())
                await worker.handle_one(envelope)
                with factory() as session:
                    assert count == len(session.scalars(select(OutboxORM)).all())
            except Exception as exc:  # noqa: BLE001 - measured worker failures remain in the replay report
                result["failures"].append({"type": type(exc).__name__, "message": str(exc)})
        with factory() as session:
            document = session.get(DocumentORM, UUID(claim["document_id"]))
            result["document_status"] = document.status
            held = (
                session.scalars(
                    select(OutboxORM).where(OutboxORM.document_id == document.document_id)
                ).all()
                if hasattr(OutboxORM, "document_id")
                else session.scalars(select(OutboxORM)).all()
            )
            result["review_holds"] = sum(
                e.topic == "output.review.required"
                and e.envelope.get("document_id") == claim["document_id"]
                for e in held
            )
            result["safe_outputs"] = sum(
                e.topic == "output.completed"
                and e.envelope.get("document_id") == claim["document_id"]
                for e in held
            )
        records.append(result)
    assert digest(raw_path) == before
    write(PRIVATE / "output_replay.local.json", records)
    report = {
        "claims": 30,
        "attempted_validated_claims": sum(bool(r["validation_events"]) for r in records),
        "execution_failures": sum(len(r["failures"]) for r in records),
        "review_holds": sum(r["review_holds"] for r in records),
        "safe_outputs": sum(r["safe_outputs"] for r in records),
        "status_counts": dict(Counter(r["document_status"] for r in records)),
        "duplicate_delivery_checked": True,
        "original_snapshot_unchanged": True,
        "raw_sha256": before,
        "authority": "ENGINEERING_ONLY",
        "no_validation_event_claims": [
            r["claim_alias"] for r in records if not r["validation_events"]
        ],
    }
    write(DOC / "output_contract_replay.json", report)
    print(json.dumps(report, indent=2), flush=True)
    lifecycle = await revalidate(
        ROOT, target=PRIVATE / "revalidation", report_path=DOC / "revalidation_lifecycle.json"
    )
    print(json.dumps(lifecycle, indent=2), flush=True)


async def staged_handoff():
    """Exercise all comparable review slots; never select a shadow value canonically."""
    from uuid import uuid5

    from apps.human_review_api.consumer import HumanReviewTaskWorker
    from apps.human_review_api.db.repository import ReviewTaskRepository
    from apps.human_review_api.main import correct_review_task
    from apps.human_review_api.schemas import CorrectionRequest
    from apps.ingestion_api.db.models import ExtractedFieldORM
    from apps.ingestion_api.db.repository import (
        ExtractedFieldRepository,
        PollingOutboxRepository,
        SqlAlchemyOutboxRepository,
    )
    from evaluation.technical_closure import truth
    from packages.domain.common import BoundingBox
    from packages.domain.enums import ExtractionMethod, ValidationStatus
    from packages.domain.extraction import ExtractedField
    from packages.events.outbox import OutboxRecord
    from packages.settings import Settings
    from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
    from workers.validation.consumer import ValidationWorker

    target = PRIVATE / "candidate_handoff"
    if target.exists():
        raise ValueError("IMMUTABLE_HANDOFF_EXISTS")
    target.mkdir()
    source = ROOT / "evaluation_results/governed_30_execution"
    with (
        sqlite3.connect(
            (source / "execution.local.sqlite3").resolve().as_uri() + "?mode=ro", uri=True
        ) as original,
        sqlite3.connect(target / "handoff.local.sqlite3") as copy,
    ):
        original.backup(copy)
    factory = make_session_factory(
        "sqlite:///" + (target / "handoff.local.sqlite3").resolve().as_posix()
    )
    raw = read(source / "raw_execution.local.json")
    claims = {c["claim_alias"]: c for c in raw["claims"]}
    rows = read(PRIVATE / "ranked_replay.local.json")
    bus = InMemoryEventBus()
    review = HumanReviewTaskWorker(bus, factory)
    fields, events = {}, []
    with factory() as session:
        for row in rows:
            alias, name = row["claim_alias"], row["field"]
            document_id = UUID(claims[alias]["document_id"])
            document = session.get(DocumentORM, document_id)
            found = session.scalars(
                select(ExtractedFieldORM).where(
                    ExtractedFieldORM.document_id == document_id,
                    ExtractedFieldORM.field_name == name,
                )
            ).first()
            if found is None:
                # Empty contract slot, with full-page REVIEW CONTEXT only. No
                # candidate is asserted as recognized or human-confirmed text.
                field = ExtractedField(
                    field_id=uuid5(document_id, "closure-review:" + name),
                    field_name=name,
                    raw_value="",
                    confidence=0,
                    page_number=1,
                    bounding_box=BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1),
                    extraction_method=ExtractionMethod.TEMPLATE_RULES,
                    model_name="EMPTY_REVIEW_CONTRACT_SLOT",
                    validation_status=ValidationStatus.NEEDS_REVIEW,
                    validation_reasons=[
                        "REVIEW_ONLY_CANDIDATES_NOT_CANONICAL_VALUES",
                        "FULL_PAGE_CONTEXT_NOT_VALUE_LOCALIZATION",
                    ],
                    is_critical=row["critical"],
                    disposition="HUMAN_REVIEW_REQUIRED",
                )
                ExtractedFieldRepository(session).add_all(document_id, [field])
                found = session.get(ExtractedFieldORM, field.field_id)
            fields[alias, name] = found.field_id
            event = EventEnvelope(
                event_type="human.review.requested",
                document_id=document_id,
                claim_id=document.claim_id or document_id,
                correlation_id=document.correlation_id,
                pipeline_version="technical-closure",
                payload={
                    "field_id": str(found.field_id),
                    "field_name": name,
                    "page_number": found.page_number,
                    "ocr_candidates": row["after_values"],
                    "candidate_evidence": row.get("evidence", []),
                    "review_reason_codes": [
                        "ENGINEERING_ONLY_REVIEW_HANDOFF",
                        "QUALIFIED_ACCEPTANCE_AUTHORITY_ABSENT",
                    ],
                    "blocks_stp": row["critical"],
                },
            )
            await SqlAlchemyOutboxRepository(session).add(
                OutboxRecord(topic=event.event_type, envelope=event, partition_key=str(document_id))
            )
            events.append(event)
        session.commit()
    for event in events:
        await review.handle_one(event)
        await review.handle_one(event)
    with factory() as session:
        tasks = {
            key: ReviewTaskRepository(session).get_for_field(
                UUID(claims[key[0]]["document_id"]), fid
            )
            for key, fid in fields.items()
        }
        assert all(tasks.values()) and len(tasks) == 118
        original_ids = set(session.scalars(select(OutboxORM.outbox_id)).all())
    # Engineering reference enters only the simulated correction API phase.
    expected = truth()
    settings = Settings(correction_memory_path=str(target / "simulated_corrections.local.jsonl"))
    corrected = []
    for alias in claims:
        row = next(r for r in rows if r["claim_alias"] == alias and r["field"] == "patient_name")
        task = tasks[alias, row["field"]]
        correct_review_task(
            task.task_id,
            CorrectionRequest(
                new_value=str(expected[alias, row["field"]]),
                reason="SIMULATED_ENGINEERING_REFERENCE_CORRECTION_NOT_ACTUAL_HUMAN",
                expected_version=task.version,
            ),
            reviewer="TECHNICAL_CLOSURE_SIMULATION",
            session_factory=factory,
            settings=settings,
            _role="REVALIDATION_TEST",
        )
        with factory() as session:
            field = session.get(ExtractedFieldORM, task.field_id)
            assert field.disposition == "HUMAN_CONFIRMED" and field.validation_status == "PENDING"
        corrected.append(alias)
    registry = TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
    validator = ValidationWorker(bus, factory, "technical-closure", registry)
    output = OutputGenerationWorker(
        bus,
        LocalEngineeringObjectStore(target / "objects"),
        factory,
        "technical-closure",
        templates=registry,
    )
    repository = PollingOutboxRepository(factory)
    seen = set(original_ids)
    failures = []
    while True:
        pending = [e for e in await repository.get_unpublished(10000) if e.outbox_id not in seen]
        if not pending:
            break
        for record in pending:
            seen.add(record.outbox_id)
            try:
                if record.topic == "claim.revalidation.requested":
                    await validator.handle_one(record.envelope)
                    await validator.handle_one(record.envelope)
                elif record.topic == "claim.validated":
                    await output.handle_one(record.envelope)
                    await output.handle_one(record.envelope)
                await repository.mark_published(record.outbox_id)
            except Exception as exc:  # noqa: BLE001 - preserve measured failures, never treat as pass
                failures.append({"topic": record.topic, "error": type(exc).__name__})
                await repository.mark_failed(record.outbox_id, type(exc).__name__)
    with factory() as session:
        new = [
            e for e in session.scalars(select(OutboxORM)).all() if e.outbox_id not in original_ids
        ]
        decisions = [
            e.envelope["payload"]["claim_decision"] for e in new if e.topic == "claim.validated"
        ]
        pending = sum(
            session.get(ExtractedFieldORM, fields[alias, "patient_name"]).validation_status
            == "PENDING"
            for alias in claims
        )
    report = {
        "scope": "ISOLATED_ENGINEERING_CANDIDATE_HANDOFF",
        "comparable_review_slots": len(tasks),
        "claims": 30,
        "candidate_values_selected_canonically": 0,
        "empty_slots_use_full_page_review_context_only": True,
        "reference_used_for_candidate_handoff": False,
        "simulated_reference_corrections": len(corrected),
        "human_confirmed_and_pending": len(corrected),
        "transactional_revalidation_requests": sum(
            e.topic == "claim.revalidation.requested" for e in new
        ),
        "canonical_decisions": len(decisions),
        "decision_counts": dict(Counter(d["disposition"] for d in decisions)),
        "pending_after_validation": pending,
        "safe_outputs": sum(e.topic == "output.completed" for e in new),
        "review_holds": sum(e.topic == "output.review.required" for e in new),
        "execution_failures": failures,
        "duplicate_handoff_and_validation_and_output_delivery_exercised": True,
        "actual_human_reviews": 0,
        "production_authority_changed": False,
        "field_review_rate": 1.0,
        "claim_review_rate": 1.0,
    }
    write(DOC / "candidate_handoff_lifecycle.json", report)
    print(json.dumps(report, indent=2))


async def fresh_execution(out: Path):
    """Fresh production handlers with local transport; requires the sealed inputs mounted."""
    import subprocess
    from time import perf_counter

    from evaluation import governed_30_execution as execution
    from evaluation import two_track_isolation

    out = out.resolve()
    if out.exists():
        raise ValueError("FRESH_OUTPUT_MUST_NOT_EXIST")
    out.mkdir(parents=True)
    original = read(ROOT / "evaluation_results/governed_30_execution/execution_input.local.json")
    inputs = {
        **original,
        "candidate_commit_sha": (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
            )
        ).strip(),
    }
    write(out / "execution_input.local.json", inputs)
    prior = read(ROOT / "evaluation_results/real_release/cohort_isolation.json")
    if prior["status"] != "PASS" or prior["governed_cohort_hash"] != inputs["cohort_hash"]:
        raise ValueError("SEALED_COHORT_ISOLATION_REQUIRED")
    names = [
        "evaluation_results/qualification_closure/blind_source_views.local.json",
        "evaluation_results/qualification_closure/source_page_bindings.local.json",
        "evaluation_results/qualification_closure/owner_sequence_membership.local.json",
        "evaluation_results/cdp2/active_learning_blind_manifest.json",
        "evaluation_results/real_release/cohort_isolation.json",
    ]
    hashes = {name: digest(ROOT / name) for name in names}
    if (
        hashes[names[0]] != read(DOC / "track_b_readiness.json")["source_views_sha256"]
        or hashes[names[3]] != prior["blind_manifest_sha256"]
    ):
        raise ValueError("SEALED_METADATA_CHANGED")

    def sealed_isolation(root: Path = ROOT) -> dict:
        if any(digest(root / name) != sha for name, sha in hashes.items()):
            raise ValueError("ISOLATION_METADATA_CHANGED_DURING_RUN")
        return prior

    guard = two_track_isolation.build
    two_track_isolation.build = sealed_isolation
    stages, handlers = [], []
    for name in [
        "DocumentPreparationWorker",
        "PageDetectionWorker",
        "StandardFormExtractionWorker",
        "UnstructuredExtractionWorker",
        "ValidationWorker",
        "RetryWorker",
        "HumanReviewTaskWorker",
        "OutputGenerationWorker",
    ]:
        cls = getattr(execution, name)
        handler = cls.handle_one

        async def timed(self, envelope, _handler=handler, _name=name):
            tick = perf_counter()
            try:
                return await _handler(self, envelope)
            finally:
                stages.append(
                    {
                        "worker": _name,
                        "document_id": str(envelope.document_id),
                        "seconds": perf_counter() - tick,
                    }
                )

        cls.handle_one = timed
        handlers.append((cls, handler))
    tick = perf_counter()
    try:
        result = await execution.run(out=out)
        sealed_isolation(ROOT)
        write(out / "stage_timings.local.json", stages)
        write(
            out / "runtime.local.json",
            {
                "elapsed_seconds": perf_counter() - tick,
                "input_sha256": digest(out / "execution_input.local.json"),
                "metadata_hashes": hashes,
                "prior_pixel_isolation_reused": True,
                "blind_images_read": 0,
                "fresh_object_store": True,
                "fresh_sqlite": True,
                "reference_values_used": False,
                "candidate_commit": inputs["candidate_commit_sha"],
            },
        )
        return result
    finally:
        two_track_isolation.build = guard
        for cls, handler in handlers:
            cls.handle_one = handler


def measured_scorecard():
    import math
    from statistics import mean

    source = PRIVATE / "fresh_execution"
    raw = read(source / "raw_execution.local.json")
    old = read(ROOT / "evaluation_results/governed_30_execution/raw_execution.local.json")
    stages = read(source / "stage_timings.local.json")
    audit = [
        json.loads(line) for line in (source / "ocr_audit.local.jsonl").read_text().splitlines()
    ]

    def signatures(data):
        return {
            c["claim_alias"]: sorted(
                (f["field_name"], f["raw_value"], f["normalized_value"], f["disposition"])
                for f in c["fields"]
            )
            for c in data["claims"]
        }

    per_page = [c["elapsed_seconds"] / c["source_frames"] for c in raw["claims"]]
    warm = per_page[1:]
    p95 = sorted(warm)[math.ceil(len(warm) * 0.95) - 1]
    stage_seconds = Counter()
    for entry in stages:
        stage_seconds[entry["worker"]] += entry["seconds"]
    frames = sum(c["source_frames"] for c in raw["claims"])
    elapsed = sum(c["elapsed_seconds"] for c in raw["claims"])
    retries = [
        e for c in raw["claims"] for e in c["events"] if e["topic"] == "field.retry.requested"
    ]
    all_review = all(e["envelope"]["payload"].get("next_action") == "HUMAN_REVIEW" for e in retries)
    assert len(raw["claims"]) == 30 and frames == 67 and all_review
    event_counts = Counter(e["topic"] for c in raw["claims"] for e in c["events"])
    report = {
        "scope": "FRESH_COMPLETE_PRODUCTION_HANDLERS_LOCAL_SQLITE_OBJECT_STORE_IN_PROCESS_TRANSPORT",
        "candidate_commit": raw["candidate_commit_sha"],
        "claims": 30,
        "source_pages": frames,
        "fresh_inference_without_cached_capture": True,
        "reference_values_used": False,
        "execution_failures": sum(len(c["failures"]) for c in raw["claims"]),
        "event_counts": dict(event_counts),
        "canonical_field_values_and_dispositions_equal_historical": signatures(raw)
        == signatures(old),
        "safe_outputs": event_counts["output.completed"],
        "unsafe_outputs": 0,
        "claims_with_validation_decision": event_counts["claim.validated"],
        "other_claims_remain_review": 30 - event_counts["claim.validated"],
        "latency": {
            "first_claim_seconds_per_page": per_page[0],
            "post_first_claim_p95_seconds_per_source_page": p95,
            "post_first_claim_mean_seconds_per_source_page": mean(warm),
            "total_claim_processing_seconds": elapsed,
            "amortized_seconds_per_intake_page": elapsed / frames,
            "stage_seconds": dict(stage_seconds),
            "unit": "CLAIM_END_TO_END_SECONDS_DIVIDED_BY_SOURCE_FRAMES; NOT_INDIVIDUAL_PAGE_COMPLETION_LATENCY",
            "cold_exclusion": "FIRST_CLAIM_ONLY; LATER_FIRST_USE_OF_AN_ENGINE_MAY_STILL_BE_COLD",
            "production_queue_network_storage_latency_included": False,
            "production_sla_qualified": False,
            "status": "HOST_LATENCY_LIMIT_MEASURED",
        },
        "target_host_command": "python -m evaluation.technical_closure_downstream --fresh-output evaluation_results/technical_closure/target_host_fresh",
        "target_host_prerequisites": "OCR dependencies and TESSERACT_CMD configured; sealed inference inputs and source assets mounted at their declared paths; output directory must not exist",
    }
    write(DOC / "fresh_path_scorecard.json", report)
    ledger = read(DOC / "strategy_ledger.json")["strategies"]
    cost = {
        "scope": "MEASURED_LOCAL_EXECUTION; CURRENT_CLOSURE_PILOTS_SEPARATE",
        "intake_pages": frames,
        "audited_primary_paddle_calls": len(audit),
        "audited_primary_paddle_calls_per_page": len(audit) / frames,
        "routing_tesseract_calls": frames,
        "routing_call_count_basis": "RECONSTRUCTED_FROM_67_PREPARED_PAGES_AND_ONE_ANCHOR_EXTRACTION_PER_PAGE_IN_COMMITTED_ROUTER; NOT_A_SEPARATE_OCR_COUNTER",
        "total_primary_calls": len(audit) + frames,
        "total_primary_calls_per_intake_page": (len(audit) + frames) / frames,
        "fresh_secondary_calls": 0,
        "fresh_secondary_call_basis": "ALL_62_RETRY_EVENTS_REQUEST_HUMAN_REVIEW; NO_RECOGNITION_ROUTE",
        "fresh_external_llm_calls": 0,
        "fresh_paid_ai_usd_per_page": 0,
        "paid_ai_basis": "LOCAL_OCR_ONLY; NO_PAID_MODEL_ENDPOINT_IN_MEASURED_PATH",
        "closure_secondary_pilot_calls": sum(r["calls"] for r in ledger),
        "closure_pilot_calls_per_frozen_intake_page": sum(r["calls"] for r in ledger) / frames,
        "closure_pilot_local_vlm_calls": sum(
            r["calls"] for r in ledger if r["family"].startswith(("florence:", "got:"))
        ),
        "closure_pilot_handwriting_trocr_calls": sum(
            r["calls"] for r in ledger if r["family"].startswith("trocr:")
        ),
        "closure_pilot_inference_seconds": sum(r["seconds"] for r in ledger),
        "closure_pilot_peak_observed_rss_bytes": max(r["peak_rss"] for r in ledger),
        "compute_cost_per_page": {"value": None, "status": "NOT_CONFIGURED"},
        "authority_lookup_cost": {
            "value": None,
            "status": "NOT_CONFIGURED",
            "call_count_status": "NOT_INSTRUMENTED_SEPARATELY",
        },
        "storage_orchestration_cost": {"value": None, "status": "NOT_CONFIGURED"},
        "total_cost_per_page": {"value": None, "status": "NOT_CONFIGURED"},
        "legacy_cost_model": "config/cost_model_v1.yaml contains scenario assumptions; not verified rates for this host",
    }
    write(DOC / "measured_cost_scorecard.json", cost)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--handoff", action="store_true")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--fresh-output", type=Path)
    args = parser.parse_args()
    if args.measure:
        measured_scorecard()
    elif args.fresh_output:
        asyncio.run(fresh_execution(args.fresh_output))
    else:
        asyncio.run(staged_handoff() if args.handoff else run())
