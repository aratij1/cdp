"""Page classification results."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow
from packages.domain.enums import ClassificationMethod, PageRole
from packages.domain.registration import RegistrationEvidence


class PageClassification(DomainModel):
    page_id: UUID
    document_id: UUID
    classification_id: UUID = Field(default_factory=new_id)
    role: PageRole
    confidence: float = Field(ge=0, le=1)
    method: ClassificationMethod
    template_id: str | None = None
    template_version: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    classified_at: datetime = Field(default_factory=utcnow)
    needs_review: bool = False
    registration_evidence: RegistrationEvidence | None = None
