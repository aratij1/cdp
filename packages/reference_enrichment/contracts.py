from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceTier(StrEnum):
    TIER_A_REFERENCE = "TIER_A_REFERENCE"
    TIER_A_APPROVED_CORRECTION = "TIER_A_APPROVED_CORRECTION"
    TIER_B_DOWNSTREAM = "TIER_B_DOWNSTREAM"
    TRAINING_ONLY = "TRAINING_ONLY"
    REJECTED = "REJECTED"
    UNVERIFIED = "UNVERIFIED"


class ReferenceLookupRequest(StrictModel):
    request_id: str
    identity_key: str
    document_id: str
    page_number: int
    document_family: str
    field_name: str
    criticality: str
    current_candidate: str | None = None
    available_claim_attributes: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    policy_version: str


class ReferenceRecord(StrictModel):
    provider_name: str
    provider_type: str
    provider_authorized: bool
    dataset_version: str | None = None
    source_record_id: str
    source_lineage: list[str]
    source_created_at: datetime | None = None
    source_finalized_at: datetime | None = None
    independent_truth: bool
    non_circular_lineage: bool
    reference_attributes: dict[str, str | None] = Field(default_factory=dict)
    field_values: dict[str, str | None] = Field(default_factory=dict)
    record_status: str
    response_hash: str
    snapshot_timestamp: datetime | None = None
    snapshot_checksum: str | None = None


class ReferenceDecision(StrictModel):
    identity_key: str
    current_candidate: str | None = None
    reference_value: str | None = None
    normalized_reference_value: str | None = None
    decision: str
    source_tier: SourceTier
    label_status: str
    reference_provider: str | None = None
    provider_authorized: bool = False
    reference_dataset_version: str | None = None
    snapshot_timestamp: datetime | None = None
    snapshot_checksum: str | None = None
    source_record_id: str | None = None
    source_lineage: list[str] = Field(default_factory=list)
    independent_truth: bool = False
    non_circular_lineage: bool = False
    matching_attributes: list[str] = Field(default_factory=list)
    match_scores: dict[str, float] = Field(default_factory=dict)
    multi_attribute_match: bool = False
    contradictions: list[str] = Field(default_factory=list)
    downstream_finalized: bool = False
    field_mapping_verified: bool = False
    approval_method: str | None = None
    second_approval_requirement: str | None = None
    primary_approved_by: str | None = None
    primary_approved_at: datetime | None = None
    second_approved_by: str | None = None
    second_approved_at: datetime | None = None
    claim_revalidated: bool = False
    evaluation_eligible: bool = False
    policy_version: str
    system_decision_id: str
    decision_reason: str
    created_at: datetime


class ReferenceResolution(StrictModel):
    """An immutable value trail; reference corrections never replace raw OCR."""

    field_name: str
    raw_value: str | None = None
    normalized_value: str | None = None
    reference_candidate: str | None = None
    corrected_value: str | None = None
    final_value: str | None = None
    correction_reason: str | None = None
    reference_source: str | None = None
    reference_version: str | None = None
    matching_attributes: list[str] = Field(default_factory=list)
    conflicting_attributes: list[str] = Field(default_factory=list)
    reference_confidence: float = Field(default=0.0, ge=0, le=1)
    decision: ReferenceDecision
