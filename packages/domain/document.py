"""Document and Page aggregates."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, ObjectRef, new_id, utcnow
from packages.domain.enums import BundleType, CompressionType, DocumentStatus, SourceFormat
from packages.image_quality.contracts import ImageQualityEvidence


class PageTransform(DomainModel):
    """A single, recorded preprocessing step applied to a page.

    Original evidence is never overwritten; every transform produces a new
    derived artifact and is appended here for auditability.
    """

    step: str
    applied_at: datetime = Field(default_factory=utcnow)
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)
    output_object: ObjectRef


class Page(DomainModel):
    """One page of a Document, after decode."""

    page_id: UUID = Field(default_factory=new_id)
    document_id: UUID
    page_number: int = Field(ge=1)
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    compression: CompressionType
    original_object: ObjectRef
    extraction_object: ObjectRef | None = None
    thumbnail_object: ObjectRef | None = None
    perceptual_hash: str | None = None
    transforms: list[PageTransform] = Field(default_factory=list)
    role: str | None = None  # set once classified; PageRole value
    image_quality: ImageQualityEvidence | None = None


class Document(DomainModel):
    """An ingested source file (may contain multiple pages)."""

    document_id: UUID = Field(default_factory=new_id)
    tenant_id: str
    correlation_id: UUID = Field(default_factory=new_id)
    source_filename: str
    detected_format: SourceFormat
    bundle_type: BundleType | None = None
    sha256: str
    page_count: int = Field(ge=0, default=0)
    status: DocumentStatus = DocumentStatus.RECEIVED
    original_object: ObjectRef
    pipeline_version: str
    schema_version: str
    received_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    claim_id: UUID | None = None

    @property
    def idempotency_key(self) -> str:
        return f"{self.sha256}:{self.pipeline_version}:{self.schema_version}"
