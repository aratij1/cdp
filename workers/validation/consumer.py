"""Validation Worker Consumer: consumes `extraction.completed`, converts
extracted fields into a canonical `Claim` domain model, evaluates field
rules and confidence thresholds via `ValidationEngine`, and outboxes either
`claim.validated` or `human.review.requested` events.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from apps.ingestion_api.db.mappers import orm_to_extracted_field
from apps.ingestion_api.db.models import ExtractedFieldORM
from apps.ingestion_api.db.repository import (
    DocumentRepository,
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
            
            # Map validation results by field_id
            results_by_field_id = {}
            for res in validation_results:
                if res.field_id:
                    results_by_field_id.setdefault(res.field_id, []).append(res)
            
            needs_retry_count = 0
            
            # Process each field
            for r in rows:
                field = orm_to_extracted_field(r)
                field_results = results_by_field_id.get(field.field_id, [])
                
                # Check if hard validation passes
                reasons = []
                for rule_res in field_results:
                    if rule_res.status in (ValidationStatus.INVALID, ValidationStatus.NEEDS_REVIEW):
                        reasons.append(rule_res.rule_name)
                        from packages.domain.enums import FieldCriticality
                        from packages.observability.metrics import validation_failure_total
                        validation_failure_total.labels(
                            rule_name=rule_res.rule_name,
                            criticality="critical" if self._validation_engine._criticality(field.field_name) == FieldCriticality.CRITICAL else "non_critical"
                        ).inc()
                
                hard_validation_passed = len(reasons) == 0
                
                # Determine criticality
                from packages.domain.enums import FieldCriticality
                is_critical = self._validation_engine._criticality(field.field_name) == FieldCriticality.CRITICAL
                r.is_critical = is_critical
                
                disposition = "NEEDS_RETRY"
                
                if hard_validation_passed:
                    disposition = "VALIDATED_AUTOMATICALLY"
                
                r.disposition = disposition
                r.validation_status = "VALID" if disposition == "VALIDATED_AUTOMATICALLY" else "NEEDS_REVIEW"
                
                if disposition == "NEEDS_RETRY":
                    needs_retry_count += 1
                    retry_envelope = EventEnvelope(
                        event_type=Topic.FIELD_RETRY_REQUESTED.value,
                        correlation_id=envelope.correlation_id,
                        document_id=document_id,
                        claim_id=claim.claim_id,
                        pipeline_version=self._pipeline_version,
                        payload={
                            "field_id": str(field.field_id),
                            "field_name": field.field_name,
                        },
                    )
                    await outbox.add(
                        OutboxRecord(
                            topic=Topic.FIELD_RETRY_REQUESTED.value,
                            envelope=retry_envelope,
                            partition_key=str(document_id),
                        )
                    )
            
            # Outbox claim.validated when done
            completed_envelope = EventEnvelope(
                event_type=Topic.CLAIM_VALIDATED.value,
                correlation_id=envelope.correlation_id,
                document_id=document_id,
                claim_id=claim.claim_id,
                pipeline_version=self._pipeline_version,
                payload={
                    "document_id": str(document_id),
                    "needs_retry_count": needs_retry_count,
                    "tenant_id": document.tenant_id,
                    "form_type": form_type.value,
                    "validation_results_count": len(validation_results),
                },
            )
            await outbox.add(
                OutboxRecord(
                    topic=Topic.CLAIM_VALIDATED.value,
                    envelope=completed_envelope,
                    partition_key=str(document_id),
                )
            )

            document.status = DocumentStatus.VALIDATING if needs_retry_count > 0 else DocumentStatus.COMPLETED
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
