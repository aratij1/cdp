"""API-facing response models — deliberately separate from the internal
canonical `packages.domain.Document` so the wire contract can evolve
independently of the domain model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from packages.domain.document import Document
from packages.domain.extraction import ExtractedField


class DocumentResponse(BaseModel):
    document_id: UUID
    status: str
    detected_format: str
    sha256: str
    page_count: int
    source_filename: str
    received_at: datetime
    is_new_document: bool
    claim_id: UUID | None = None
    patient_name: str | None = None

    @classmethod
    def from_domain(cls, document: Document, is_new: bool, patient_name: str | None = None) -> DocumentResponse:
        return cls(
            document_id=document.document_id,
            status=document.status.value,
            detected_format=document.detected_format.value,
            sha256=document.sha256,
            page_count=document.page_count,
            source_filename=document.source_filename,
            received_at=document.received_at,
            is_new_document=is_new,
            claim_id=document.claim_id,
            patient_name=patient_name,
        )


class ExtractedFieldResponse(BaseModel):
    field_name: str
    value: str
    normalized_value: str | None
    confidence: float
    page_number: int
    bounding_box: dict[str, float]
    extraction_method: str
    validation_status: str
    validation_reasons: list[str]

    @classmethod
    def from_domain(cls, field: ExtractedField) -> ExtractedFieldResponse:
        return cls(
            field_name=field.field_name,
            value=field.raw_value,
            normalized_value=field.normalized_value,
            confidence=field.confidence,
            page_number=field.page_number,
            bounding_box=field.bounding_box.model_dump(),
            extraction_method=field.extraction_method.value,
            validation_status=field.validation_status.value,
            validation_reasons=field.validation_reasons,
        )


class DocumentResultResponse(BaseModel):
    document: DocumentResponse
    fields: list[ExtractedFieldResponse]
    field_count: int
    processing_complete: bool
