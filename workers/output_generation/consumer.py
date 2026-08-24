"""Output Generation Worker Consumer: consumes `claim.validated`, generates
all configured output artifacts (Canonical JSON, Evidence Manifest,
Reconciliation Report, and Fixed-Width NSF), persists them to Object Storage,
updates document status to `OUTPUT_GENERATED`, and outboxes `output.generated`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.mappers import orm_to_extracted_field
from apps.ingestion_api.db.models import ExtractedFieldORM
from apps.ingestion_api.db.repository import (
    DocumentRepository,
    SqlAlchemyOutboxRepository,
)
from packages.claim_decision import (
    ClaimDecision,
    ClaimDecisionContext,
    ClaimDecisionService,
)
from packages.claim_evidence import ClaimEvidenceResult
from packages.domain.claim import Claim, ServiceLine
from packages.domain.enums import ClaimFormType, DocumentStatus
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.evidence_decision import (
    FieldDecision,
    FieldDisposition,
    NextAction,
)
from packages.fixed_width.spec_loader import load_nsf_specs
from packages.runtime_profile import DecisionServiceFactory
from packages.storage.object_store import ObjectStore
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from packages.validation_rules.engine import ValidationEngine
from packages.validation_rules.thresholds import ThresholdRegistry
from workers.output_generation.canonical_json import to_canonical_json_bytes
from workers.output_generation.evidence_manifest import build_evidence_manifest
from workers.output_generation.nsf_output import NSFOutputWriter
from workers.output_generation.reconciliation_report import build_reconciliation_report

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "output-generation-worker"


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)
        return super().default(o)


class OutputGenerationWorker:
    def __init__(
        self,
        event_bus: EventBus,
        object_store: ObjectStore,
        session_factory: sessionmaker,
        pipeline_version: str,
        bucket: str = "idp-documents",
        templates: TemplateRegistry | None = None,
        claim_decision_service: ClaimDecisionService | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._object_store = object_store
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._bucket = bucket
        self._templates = templates or TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)
        self._claim_decision_service = (
            claim_decision_service or DecisionServiceFactory.from_profile().claim_decision
        )
        self._validation_engine = ValidationEngine(ThresholdRegistry.load_from_directory())
        try:
            specs = load_nsf_specs()
            self._nsf_writer = NSFOutputWriter(specs)
        except (OSError, ValueError):
            self._nsf_writer = NSFOutputWriter({})

    async def handle_one(self, envelope: EventEnvelope) -> None:
        document_id = envelope.document_id
        if document_id is None:
            logger.warning("claim.validated event missing document_id, skipping")
            return

        with self._session_factory() as session:
            documents = DocumentRepository(session)
            outbox = SqlAlchemyOutboxRepository(session)

            document = documents.get(document_id)
            if document is None:
                logger.warning("document %s not found, skipping output generation", document_id)
                return

            stmt = (
                select(ExtractedFieldORM)
                .where(ExtractedFieldORM.document_id == document_id)
                .order_by(ExtractedFieldORM.page_number)
            )
            rows = session.execute(stmt).scalars().all()

            header_fields = []
            service_lines_map: dict[int, list] = {}

            for r in rows:
                field = orm_to_extracted_field(r)
                if r.service_line_number is None:
                    header_fields.append(field)
                else:
                    service_lines_map.setdefault(r.service_line_number, []).append(field)

            service_lines = [
                ServiceLine(line_number=line_num, fields=f_list)
                for line_num, f_list in sorted(service_lines_map.items())
            ]

            claim_id = document.claim_id or document_id
            from packages.templates.selection import (
                exact_family_template,
                form_type_from_output_context,
            )
            form_type = form_type_from_output_context(
                envelope.payload.get("form_type"), document.bundle_type
            )
            template = exact_family_template(self._templates, form_type)

            total_charge_val = None
            total_charge_field = next((f for f in header_fields if f.field_name == "total_charge"), None)
            if total_charge_field and total_charge_field.raw_value:
                try:
                    total_charge_val = Decimal(total_charge_field.raw_value.replace("$", "").replace(",", "").strip())
                except (InvalidOperation, ValueError):
                    logger.warning("invalid total charge on document %s", document_id)

            if service_lines and total_charge_val is not None and not any(l.charge_amount for l in service_lines):
                service_lines[0].charge_amount = total_charge_val
            elif not service_lines and total_charge_val is not None:
                service_lines = [ServiceLine(line_number=1, charge_amount=total_charge_val)]

            claim = Claim(
                claim_id=claim_id,
                document_id=document_id,
                tenant_id=document.tenant_id,
                correlation_id=envelope.correlation_id,
                form_type=form_type,
                total_charge_amount=total_charge_val,
                schema_version=document.schema_version,
                header_fields=header_fields,
                service_lines=service_lines,
            )

            claim_decision_payload = envelope.payload.get("claim_decision")
            if claim_decision_payload:
                claim_decision = ClaimDecision.model_validate(claim_decision_payload)
                if (
                    claim_decision.claim_id != str(claim_id)
                    or claim_decision.policy_id != self._claim_decision_service.policy_id
                    or claim_decision.policy_version != self._claim_decision_service.policy_version
                ):
                    raise ValueError("Cannot finalize claim: invalid canonical claim-decision provenance")
                serialized_field_decisions = envelope.payload.get("field_decisions")
                if serialized_field_decisions is not None:
                    evidence_payload = envelope.payload.get("claim_evidence") or {
                        "evidence_items": [], "contradictions": [],
                    }
                    claim_evidence = ClaimEvidenceResult.model_validate(evidence_payload)
                    recomputed = self._claim_decision_service.decide(ClaimDecisionContext(
                        claim_id=str(claim_id),
                        document_family=form_type.value,
                        field_decisions=[
                            FieldDecision.model_validate(item)
                            for item in serialized_field_decisions
                        ],
                        claim_evidence=claim_evidence.evidence_items,
                        contradictions=claim_evidence.contradictions,
                        policy_id=self._claim_decision_service.policy_id,
                        policy_version=self._claim_decision_service.policy_version,
                        dependent_field_groups=(
                            [["total_charge", "charges", "charge_amount"]]
                            if form_type is ClaimFormType.CMS1500 else
                            [["revenue_code", "hcpcs_code", "units", "charges", "charge_amount"]]
                        ),
                    ))
                    if recomputed.model_dump(mode="json") != claim_decision.model_dump(mode="json"):
                        raise ValueError(
                            "Cannot finalize claim: canonical claim-decision parity check failed"
                        )
            else:
                field_decisions = []
                for row in rows:
                    policy = self._claim_decision_service.field_policy.for_field(
                        form_type.value, row.field_name,
                    )
                    try:
                        disposition = FieldDisposition(row.disposition)
                    except (TypeError, ValueError):
                        disposition = FieldDisposition.INSUFFICIENT_EVIDENCE
                    field_decisions.append(FieldDecision(
                        field_id=str(row.field_id),
                        field_name=row.field_name,
                        selected_value=row.normalized_value or row.raw_value,
                        disposition=disposition,
                        calibrated_probability=float(row.confidence or 0),
                        reason_codes=list(row.validation_reasons or []),
                        next_action=(
                            NextAction.NONE
                            if disposition in {
                                FieldDisposition.AUTO_ACCEPTED,
                                FieldDisposition.REFERENCE_CONFIRMED,
                                FieldDisposition.HUMAN_CONFIRMED,
                            }
                            else NextAction.HUMAN_REVIEW
                        ),
                        policy_version="persisted-field-disposition",
                        criticality=policy.criticality,
                        required=policy.required,
                        blocks_stp=policy.blocks_stp,
                        requires_review_when_unresolved=policy.requires_review_when_unresolved,
                    ))
                claim_decision = self._claim_decision_service.decide(ClaimDecisionContext(
                    claim_id=str(claim_id),
                    document_family=form_type.value,
                    field_decisions=field_decisions,
                    policy_id=self._claim_decision_service.policy_id,
                    policy_version=self._claim_decision_service.policy_version,
                ))
            if not claim_decision.stp_eligible:
                logger.error(
                    "Canonical finalization gate failed for %s: %s (%s)",
                    claim_id, claim_decision.disposition.value,
                    ",".join(claim_decision.blocking_unresolved_fields),
                )
                raise ValueError(
                    "Cannot finalize claim: unresolved critical/blocking fields; "
                    f"canonical disposition is {claim_decision.disposition.value}"
                )

            validation_results = self._validation_engine.validate_claim(claim, template)

            # Generate outputs
            canonical_bytes = to_canonical_json_bytes(claim)
            evidence_bytes = json.dumps(build_evidence_manifest(claim), indent=2).encode("utf-8")
            recon_report = build_reconciliation_report(claim, validation_results)
            reconciliation_bytes = json.dumps(dataclasses.asdict(recon_report), indent=2, cls=DecimalEncoder).encode("utf-8")
            nsf_records = self._nsf_writer.render_available_records(claim)
            nsf_bytes = "\n".join(nsf_records).encode("utf-8") if nsf_records else b""

            prefix = f"outputs/{document.tenant_id}/{claim_id}"
            json_key = f"{prefix}/canonical_claim.json"
            evidence_key = f"{prefix}/evidence_manifest.json"
            reconciliation_key = f"{prefix}/reconciliation_report.json"
            nsf_key = f"{prefix}/claim_output.nsf"

            self._object_store.put_immutable(self._bucket, json_key, canonical_bytes, "application/json")
            self._object_store.put_immutable(self._bucket, evidence_key, evidence_bytes, "application/json")
            self._object_store.put_immutable(self._bucket, reconciliation_key, reconciliation_bytes, "application/json")
            if nsf_bytes:
                self._object_store.put_immutable(self._bucket, nsf_key, nsf_bytes, "text/plain")

            document.status = DocumentStatus.OUTPUT_GENERATED
            document.updated_at = datetime.now(UTC)
            documents.update(document)

            output_envelope = EventEnvelope(
                event_type=Topic.OUTPUT_COMPLETED.value,
                correlation_id=envelope.correlation_id,
                document_id=document_id,
                claim_id=claim_id,
                pipeline_version=self._pipeline_version,
                payload={
                    "document_id": str(document_id),
                    "claim_id": str(claim_id),
                    "tenant_id": document.tenant_id,
                    "canonical_json_uri": json_key,
                    "evidence_manifest_uri": evidence_key,
                    "reconciliation_report_uri": reconciliation_key,
                    "nsf_output_uri": nsf_key if nsf_bytes else None,
                    "claim_decision": claim_decision.model_dump(mode="json"),
                },
            )
            await outbox.add(
                OutboxRecord(
                    topic=Topic.OUTPUT_COMPLETED.value,
                    envelope=output_envelope,
                    partition_key=str(document_id),
                )
            )

            session.commit()
            logger.info("successfully generated output artifacts for document %s", document_id)

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.CLAIM_VALIDATED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception("failed to generate output artifacts")


def main() -> None:
    from apps.ingestion_api.db.session import make_session_factory
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings
    from packages.storage.object_store import ObjectStoreSettings

    configure_logging("output-generation-worker")
    settings = get_settings()
    object_store = ObjectStore(
        ObjectStoreSettings(
            endpoint_url=settings.object_store_endpoint,
            access_key=settings.object_store_access_key,
            secret_key=settings.object_store_secret_key,
            use_ssl=settings.object_store_use_ssl,
        )
    )
    worker = OutputGenerationWorker(
        event_bus=AIOKafkaEventBus(settings.kafka_bootstrap_servers),
        object_store=object_store,
        session_factory=make_session_factory(settings.database_url),
        pipeline_version=settings.pipeline_version,
        bucket=settings.object_store_bucket,
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
