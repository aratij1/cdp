"""Schemas for the Output API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ClaimSummary(BaseModel):
    document_id: UUID
    claim_id: UUID | None = None
    tenant_id: str
    status: str
    filename: str
    received_at: datetime
    updated_at: datetime


class ClaimListResponse(BaseModel):
    items: list[ClaimSummary]
    total: int


class ClaimDetailResponse(BaseModel):
    document_id: UUID
    claim_id: UUID | None = None
    tenant_id: str
    status: str
    filename: str
    page_count: int
    received_at: datetime
    updated_at: datetime
    available_outputs: list[str]


class OutputDownloadResponse(BaseModel):
    claim_id: UUID
    output_type: str
    object_uri: str
    download_url: str
    expires_in_seconds: int = 3600
