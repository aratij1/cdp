"""Validation Worker Consumer: consumes `extraction.completed`, converts
extracted fields into a canonical `Claim` domain model, evaluates field
rules and confidence thresholds via `ValidationEngine`, and outboxes either
`claim.validated` or `human.review.requested` events.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.mappers import orm_to_extracted_field
from apps.ingestion_api.db.models import ExtractedFieldORM
from apps.ingestion_api.db.repository import (
    DocumentRepository,
    ExtractedFieldRepository,
    SqlAlchemyOutboxRepository,
)
from packages.domain.claim import Claim, ServiceLine
from packages.domain.enums import ClaimFormType, DocumentStatus, ValidationStatus
from packages.events.bus import EventBus
from packages.events.envelope import EventEnvelope
from packages.events.outbox import OutboxRecord
from packages.events.topics import Topic
from packages.templates.registry import DEFAULT_TEMPLATE_DIR, TemplateRegistry
from packages.validation_rules.engine import ValidationEngine
from packages.validation_rules.thresholds import ThresholdRegistry

logger = logging.getLogger(__name__)

CONSUMER_GROUP = "validation-worker"


class ValidationWorker:
    def __init__(
        self,
        event_bus: EventBus,
        session_factory: sessionmaker,
        pipeline_version: str,
        templates: TemplateRegistry,
        validation_engine: ValidationEngine | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._session_factory = session_factory
        self._pipeline_version = pipeline_version
        self._templates = templates
        self._validation_engine = (
            validation_engine if validation_engine is not None else ValidationEngine(ThresholdRegistry.load_from_directory())
        )

    async def handle_one(self, envelope: EventEnvelope) -> None:
        document_id = envelope.document_id
        if document_id is None:
            logger.warning("extraction.completed event missing document_id, skipping")
            return

        with self._session_factory() as session:
            documents = DocumentRepository(session)
            outbox = SqlAlchemyOutboxRepository(session)

            document = documents.get(document_id)
            if document is None:
                logger.warning("document %s not found, skipping", document_id)
                return

            # Query all extracted fields with service_line_number
            from sqlalchemy import select
            stmt = (
                select(ExtractedFieldORM)
                .where(ExtractedFieldORM.document_id == document_id)
                .order_by(ExtractedFieldORM.page_number)
            )
            rows = session.execute(stmt).scalars().all()
            if not rows:
                logger.warning("document %s has no extracted fields, skipping validation", document_id)
                return

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

            # Infer template & form_type
            template_id = rows[0].template_version or "cms1500"
            form_type = (
                ClaimFormType.UB04
                if "ub" in template_id.lower()
                else ClaimFormType.CMS1500
            )

            try:
                template = self._templates.latest_for_form_type(form_type)
            except Exception:
                template = self._templates.get("cms1500", "02-12")

            total_charge_val = None
            total_charge_field = next((f for f in header_fields if f.field_name == "total_charge"), None)
            if total_charge_field and total_charge_field.raw_value:
                try:
                    from decimal import Decimal
                    total_charge_val = Decimal(total_charge_field.raw_value.replace("$", "").replace(",", "").strip())
                except Exception:
                    pass

            if service_lines and total_charge_val is not None and not any(l.charge_amount for l in service_lines):
                service_lines[0].charge_amount = total_charge_val
            elif not service_lines and total_charge_val is not None:
                service_lines = [ServiceLine(line_number=1, charge_amount=total_charge_val)]

            claim = Claim(
                claim_id=document.claim_id or document_id,
                document_id=document_id,
                tenant_id=document.tenant_id,
                correlation_id=envelope.correlation_id,
                form_type=form_type,
                total_charge_amount=total_charge_val,
                schema_version=document.schema_version,
                template_version=template.version,
                header_fields=header_fields,
                service_lines=service_lines,
            )

            validation_results = self._validation_engine.validate_claim(claim, template)

            invalid_or_review_results = [
                res for res in validation_results
                if res.status in (ValidationStatus.INVALID, ValidationStatus.NEEDS_REVIEW)
            ]

            # Emit human review requests for invalid or low-confidence fields
            for result in invalid_or_review_results:
                if result.field_id is None:
                    continue
                review_envelope = EventEnvelope(
                    event_type=Topic.HUMAN_REVIEW_REQUESTED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    claim_id=claim.claim_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "field_id": str(result.field_id),
                        "field_name": result.field_name,
                        "page_number": 1,
                        "ocr_candidates": [result.message],
                        "validation_errors": [result.message],
                    },
                )
                await outbox.add(
                    OutboxRecord(
                        topic=Topic.HUMAN_REVIEW_REQUESTED.value,
                        envelope=review_envelope,
                        partition_key=str(document_id),
                    )
                )

            if invalid_or_review_results:
                document.status = DocumentStatus.NEEDS_REVIEW
                logger.info(
                    "document %s validation failed: %d field errors -> NEEDS_REVIEW",
                    document_id,
                    len(invalid_or_review_results),
                )
            else:
                document.status = DocumentStatus.COMPLETED
                validated_envelope = EventEnvelope(
                    event_type=Topic.CLAIM_VALIDATED.value,
                    correlation_id=envelope.correlation_id,
                    document_id=document_id,
                    claim_id=claim.claim_id,
                    pipeline_version=self._pipeline_version,
                    payload={
                        "document_id": str(document_id),
                        "claim_id": str(claim.claim_id),
                        "tenant_id": document.tenant_id,
                        "form_type": form_type.value,
                        "validation_results_count": len(validation_results),
                    },
                )
                await outbox.add(
                    OutboxRecord(
                        topic=Topic.CLAIM_VALIDATED.value,
                        envelope=validated_envelope,
                        partition_key=str(document_id),
                    )
                )
                logger.info("document %s successfully validated -> VALIDATED", document_id)

            document.updated_at = datetime.now(UTC)
            documents.update(document)
            session.commit()

    async def run_forever(self) -> None:
        async for _topic, envelope in self._event_bus.subscribe(
            [Topic.EXTRACTION_COMPLETED.value], group_id=CONSUMER_GROUP
        ):
            try:
                await self.handle_one(envelope)
            except Exception:
                logger.exception("failed to validate extraction output")


def main() -> None:
    from apps.ingestion_api.db.session import make_session_factory
    from packages.events.bus import AIOKafkaEventBus
    from packages.observability import configure_logging
    from packages.settings import get_settings

    configure_logging("validation-worker")
    settings = get_settings()
    worker = ValidationWorker(
        event_bus=AIOKafkaEventBus(settings.kafka_bootstrap_servers),
        session_factory=make_session_factory(settings.database_url),
        pipeline_version=settings.pipeline_version,
        templates=TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR),
    )
    asyncio.run(worker.run_forever())


if __name__ == "__main__":
    main()
