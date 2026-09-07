"""Execute frozen qualification inputs against configured CDP services.

Run via qualification_jobs, on a designated qualification deployment. Credentials
are resolved from named environment variables; truth values are never loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

# Support the pinned absolute-script argv launched from the private job directory.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.human_review_api.db.models import ReviewTaskORM
from apps.ingestion_api.db.models import DocumentORM, ExtractedFieldORM, OutboxORM, PageORM
from evaluation.reconstruct_source_bindings import rendered_hash
from packages.events.topics import Topic
from packages.real_data_evaluation.blind_workflow import content_digest
from packages.real_data_evaluation.qualification_jobs import publish


def assemble_claim(page_ids: list[str], sources: dict) -> bytes:
    images = []
    for page in page_ids:
        source = sources[page]
        asset = Path(source["source_asset_path"])
        if hashlib.sha256(asset.read_bytes()).hexdigest() != source["source_asset_sha256"]:
            raise ValueError("SOURCE_ASSET_CHANGED")
        with Image.open(asset) as image:
            image.seek(source["frame_index"])
            frame = image.copy()
        if rendered_hash(frame) != source["rendered_page_sha256"]:
            raise ValueError("SOURCE_FRAME_CHANGED")
        images.append(frame)
    buffer = io.BytesIO()
    images[0].save(
        buffer, format="TIFF", save_all=True, append_images=images[1:], compression="tiff_deflate"
    )
    return buffer.getvalue()


def snapshot(
    session: Session, cohort: dict, mapping: dict, *, final: bool, configuration: dict
) -> dict | None:
    fields, claims, provenance = [], {}, []
    for claim_id, member in cohort["claims"].items():
        doc_id = UUID(mapping[claim_id]["document_id"])
        document = session.get(DocumentORM, doc_id)
        if document is None or document.sha256 != mapping[claim_id]["ingested_sha256"]:
            raise ValueError("INGESTION_LINEAGE_MISMATCH")
        source_pages = mapping[claim_id].get("source_pages", [])
        if [p.get("page_id") for p in source_pages] != member["page_ids"]:
            raise ValueError("SOURCE_PAGE_ORDER_BINDING_MISMATCH")
        pages = session.scalars(select(PageORM).where(PageORM.document_id == doc_id)).all()
        if {p.page_number for p in pages} != set(range(1, len(member["page_ids"]) + 1)):
            return None
        rows = session.scalars(
            select(ExtractedFieldORM).where(ExtractedFieldORM.document_id == doc_id)
        ).all()
        tasks = session.scalars(
            select(ReviewTaskORM).where(ReviewTaskORM.document_id == doc_id)
        ).all()
        events = session.scalars(
            select(OutboxORM)
            .where(OutboxORM.partition_key == str(doc_id))
            .order_by(OutboxORM.created_at, OutboxORM.outbox_id)
        ).all()
        validated = [e for e in events if e.topic == Topic.CLAIM_VALIDATED.value]
        if not validated or any(r.validation_status == "PENDING" for r in rows):
            return None
        if not final and any(t.correction_corrected_at is not None for t in tasks):
            raise ValueError("RAW_CAPTURE_AFTER_HUMAN_CORRECTION_FORBIDDEN")
        if final and any(t.status in {"OPEN", "IN_PROGRESS"} for t in tasks):
            return None
        latest = validated[-1]
        canonical_decision = latest.envelope["payload"]["claim_decision"]
        decision = canonical_decision["disposition"]
        completion_id = uuid5(NAMESPACE_URL, "cdp:output:" + latest.envelope["event_id"])
        outputs = [
            e
            for e in events
            if e.topic == Topic.OUTPUT_COMPLETED.value
            and e.outbox_id == completion_id
            and e.created_at >= latest.created_at
            and e.envelope.get("payload", {}).get("document_id") == str(doc_id)
            and e.envelope.get("payload", {}).get("claim_decision") == canonical_decision
        ]
        output_completed = bool(outputs) and document.status == "OUTPUT_GENERATED"
        human_corrected = any(t.correction_corrected_at is not None for t in tasks)
        human_reviewed = (
            human_corrected
            or any(
                t.claimed_at is not None
                or t.assigned_to is not None
                or t.status in {"IN_PROGRESS", "COMPLETED"}
                for t in tasks
            )
            or any(r.disposition == "HUMAN_CONFIRMED" for r in rows)
        )
        if not final and human_reviewed:
            raise ValueError("RAW_CAPTURE_AFTER_HUMAN_INTERVENTION_FORBIDDEN")
        # A safe decision alone is not proof that the output worker completed.
        if not final and decision == "STP_SAFE" and not output_completed:
            return None
        if final:
            requests = [e for e in events if e.topic == Topic.CLAIM_REVALIDATION_REQUESTED.value]
            completions = {e.outbox_id for e in validated}
            if any(
                uuid5(NAMESPACE_URL, "cdp:validation:" + e.envelope["event_id"]) not in completions
                for e in requests
            ):
                return None
            if decision == "STP_SAFE" and not output_completed:
                return None
        indexed = {}
        for canonical_row in rows:
            if canonical_row.service_line_number is not None:
                raise ValueError("GOVERNED_SERVICE_LINE_FIELD_MAPPING_REQUIRED")
            if not 1 <= canonical_row.page_number <= len(member["page_ids"]):
                raise ValueError("CANONICAL_FIELD_PAGE_OUT_OF_RANGE")
            key = (member["page_ids"][canonical_row.page_number - 1], canonical_row.field_name)
            if key in indexed:
                raise ValueError("AMBIGUOUS_CANONICAL_FIELD_MAPPING")
            indexed[key] = canonical_row
        expected = {tuple(k) for k in member["expected_field_keys"]}
        if set(indexed) - expected:
            raise ValueError("UNREVIEWED_CANONICAL_FIELD_DENOMINATOR")
        for page, name in sorted(expected):
            row = indexed.get((page, name))
            field_tasks = [t for t in tasks if row is not None and t.field_id == row.field_id]
            accepted = (
                row is not None
                and row.disposition in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}
                and row.validation_status == "VALID"
                and (final or (not field_tasks and row.disposition != "HUMAN_CONFIRMED"))
            )
            if (
                not final
                and not accepted
                and row is not None
                and not any(t.field_id == row.field_id for t in tasks)
            ):
                return None  # Machine retry is not yet terminal.
            canonical_page = next(
                p for p in pages if p.page_number == member["page_ids"].index(page) + 1
            )
            fields.append(
                {
                    "claim_id": claim_id,
                    "package_id": member.get("package_id"),
                    "source_sha256": next(
                        p["rendered_page_sha256"] for p in source_pages if p["page_id"] == page
                    ),
                    "document_id": str(doc_id),
                    "canonical_claim_id": str(document.claim_id or doc_id),
                    "page_id": page,
                    "canonical_page_id": str(canonical_page.page_id),
                    "page_role": getattr(canonical_page, "role", None),
                    "image_quality": getattr(canonical_page, "image_quality", None),
                    "canonical_field_id": str(row.field_id) if row else None,
                    "source_binding": "EXACT",
                    "prediction_binding": "EXACT",
                    "field_name": name,
                    "critical": row.is_critical if row else None,
                    "raw_value": row.raw_value if row else None,
                    "disposition": row.disposition if row else None,
                    "validation_reasons": row.validation_reasons if row else [],
                    "reference_evidence": row.reference_evidence if row else None,
                    "review_reason_codes": sorted(
                        {code for task in field_tasks for code in task.review_reason_codes}
                    ),
                    "human_corrected": any(
                        t.correction_corrected_at is not None for t in field_tasks
                    ),
                    "human_reviewed": any(
                        t.claimed_at is not None
                        or t.assigned_to is not None
                        or t.status in {"IN_PROGRESS", "COMPLETED"}
                        for t in field_tasks
                    ),
                    "state": "VALUE"
                    if row and (row.normalized_value or row.raw_value)
                    else "EXTRACTION_FAILED",
                    "value": (row.normalized_value or row.raw_value) if row else None,
                    "accepted": accepted,
                    "review_required": not accepted,
                }
            )
        claims[claim_id] = {
            "decision": decision,
            "human_corrected": human_corrected,
            "human_reviewed": human_reviewed,
            "human_intervention_required": bool(tasks)
            or human_reviewed
            or decision in {"FIELD_REVIEW_REQUIRED", "CLAIM_REVIEW_REQUIRED"},
            "output_completed": output_completed,
            "automatic_output_safely_generated": output_completed
            and not tasks
            and not human_reviewed
            and decision == "STP_SAFE",
            "required_fields_pass": decision == "STP_SAFE"
            and canonical_decision.get("stp_eligible") is True
            and canonical_decision.get("blocking_unresolved_fields") == []
            and canonical_decision.get("critical_blockers") == [],
            "required_evidence_pass": decision == "STP_SAFE"
            and canonical_decision.get("stp_eligible") is True
            and canonical_decision.get("contradictions") == [],
            "reason_codes": canonical_decision.get("reason_codes", []),
            "revalidation_completed": final,
            "document_id": str(doc_id),
        }
        provenance.append(
            {
                "document_id": str(doc_id),
                "claim_id": claim_id,
                "candidate_commit_sha": configuration.get("candidate_commit_sha"),
                "deployment_attestation_sha256": configuration.get("deployment_attestation_sha256"),
                "decision_event_id": latest.envelope["event_id"],
                "output_event_ids": [e.envelope["event_id"] for e in outputs],
                "source_pages": mapping[claim_id]["source_pages"],
            }
        )
    result = {
        "scope": "CANONICAL_PRODUCTION_PIPELINE",
        "purpose": "FINAL_GATE",
        "used_for_tuning": False,
        "candidate_commit_sha": configuration.get("candidate_commit_sha"),
        "configuration_sha256": configuration["pipeline_configuration_sha256"],
        "execution_provenance": provenance,
        "claims": claims,
        "fields": fields,
    }
    result["snapshot_sha256"] = content_digest(result)
    return result


def validate_execution_inputs(request: dict, cohort: dict, directory: Path) -> None:
    """Fail closed before ingestion or capture if durable job inputs were edited."""
    if request.get("contract") != "CDP_QUALIFICATION_EXECUTION_V1" or request.get(
        "request_id"
    ) != content_digest({k: v for k, v in request.items() if k != "request_id"}):
        raise ValueError("EXECUTION_REQUEST_CHANGED")
    if cohort.get("cohort_sha256") != content_digest(
        {k: v for k, v in cohort.items() if k != "cohort_sha256"}
    ) or cohort.get("cohort_sha256") != request["inputs"].get("cohort_sha256"):
        raise ValueError("EXECUTION_COHORT_CHANGED")
    if request["phase"] == "HITL_FINAL":
        raw = json.loads((directory / "raw_predictions.local.json").read_text())
        if raw.get("snapshot_sha256") != request["inputs"].get("raw_sha256") or raw.get(
            "snapshot_sha256"
        ) != content_digest({k: v for k, v in raw.items() if k != "snapshot_sha256"}):
            raise ValueError("RAW_EXECUTION_SNAPSHOT_CHANGED")


def validate_candidate_deployment(settings: dict, directory: Path) -> None:
    """Require owner-supplied deployment evidence tied to the frozen candidate."""
    freeze_path = directory / "candidate_freeze.local.json"
    if not freeze_path.exists():
        raise ValueError("FROZEN_CANDIDATE_REQUIRED")
    frozen = json.loads(freeze_path.read_text())
    candidate = frozen.get("candidate_commit_sha", "")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", candidate)
        or settings.get("candidate_commit_sha") != candidate
    ):
        raise ValueError("DEPLOYED_CANDIDATE_SHA_MISMATCH")
    attestation_path = directory / "deployment_attestation.local.json"
    if not attestation_path.exists():
        raise ValueError("DEPLOYMENT_CANDIDATE_ATTESTATION_REQUIRED")
    attestation = json.loads(attestation_path.read_text())
    if (
        content_digest(attestation) != settings.get("deployment_attestation_sha256")
        or attestation.get("candidate_commit_sha") != candidate
        or attestation.get("governed") is not True
        or not attestation.get("approval_reference")
        or not settings.get("deployment_id")
        or attestation.get("deployment_id") != settings["deployment_id"]
        or attestation.get("pipeline_configuration_sha256")
        != settings.get("pipeline_configuration_sha256")
    ):
        raise ValueError("DEPLOYMENT_CANDIDATE_ATTESTATION_INVALID")


def execute(request_path: Path, receipt_path: Path) -> None:
    request = json.loads(request_path.read_text())
    directory = request_path.parents[2]
    config = json.loads((directory / "deployment_control.local.json").read_text())
    settings = config.get("cdp_services", {})
    if config.get("governed") is not True or settings.get("qualification_environment") is not True:
        raise ValueError("GOVERNED_QUALIFICATION_DEPLOYMENT_REQUIRED")
    if content_digest(config) != request["configuration_sha256"]:
        raise ValueError("EXECUTION_CONFIGURATION_CHANGED")
    phase = request["phase"]
    if phase not in {"RAW", "HITL_FINAL"}:
        raise ValueError("UNSUPPORTED_CDP_EXECUTION_PHASE")
    cohort = json.loads((directory / "release_cohort.local.json").read_text())
    validate_execution_inputs(request, cohort, directory)
    validate_candidate_deployment(settings, directory)
    sources = {
        s["page_id"]: s
        for s in json.loads((directory / "blind_source_views.local.json").read_text())
    }
    mapping_path = directory / "deployment_document_map.local.json"
    mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    if phase == "RAW":
        headers = {}
        if settings.get("authorization_env"):
            headers["Authorization"] = os.environ[settings["authorization_env"]]
        with httpx.Client(
            base_url=settings["ingestion_url"], headers=headers, timeout=120
        ) as client:
            for claim_id, claim in cohort["claims"].items():
                if claim_id in mapping:
                    continue
                data = assemble_claim(claim["page_ids"], sources)
                response = client.post(
                    "/documents",
                    files={"file": ("qualification.tiff", data, "image/tiff")},
                    params={"tenant_id": settings["tenant_id"]},
                )
                response.raise_for_status()
                doc = response.json()
                if doc["is_new_document"] is not True:
                    raise ValueError("FRESH_QUALIFICATION_INGESTION_REQUIRED")
                mapping[claim_id] = {
                    "document_id": doc["document_id"],
                    "ingested_sha256": hashlib.sha256(data).hexdigest(),
                    "source_pages": [
                        {"page_id": p, "rendered_page_sha256": sources[p]["rendered_page_sha256"]}
                        for p in claim["page_ids"]
                    ],
                }
                temporary = mapping_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(mapping, indent=2))
                temporary.replace(mapping_path)
    if set(mapping) != set(cohort["claims"]):
        raise ValueError("COMPLETE_DEPLOYMENT_CLAIM_BINDING_REQUIRED")
    engine = create_engine(os.environ[settings["database_url_env"]], pool_pre_ping=True)
    output = directory / (
        "raw_predictions.local.json" if phase == "RAW" else "post_hitl_predictions.local.json"
    )
    try:
        while True:
            with Session(engine) as session:
                result = snapshot(
                    session, cohort, mapping, final=phase == "HITL_FINAL", configuration=settings
                )
            if result is not None:
                publish(output, result)
                receipt = {
                    "request_id": request["request_id"],
                    "status": "PASS",
                    "outputs": {output.name: hashlib.sha256(output.read_bytes()).hexdigest()},
                }
                receipt["receipt_sha256"] = content_digest(receipt)
                temporary = receipt_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(receipt))
                temporary.replace(receipt_path)
                return
            time.sleep(5)
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--qualification-request", type=Path, required=True)
    parser.add_argument("--qualification-receipt", type=Path, required=True)
    args = parser.parse_args()
    execute(args.qualification_request, args.qualification_receipt)
