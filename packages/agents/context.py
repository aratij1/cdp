from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id, utcnow


class WorkflowState(StrEnum):
    INGESTED = "INGESTED"
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    IDENTITY_RESOLUTION = "IDENTITY_RESOLUTION"
    COVERAGE_CHECK = "COVERAGE_CHECK"
    EVIDENCE_RECONCILIATION = "EVIDENCE_RECONCILIATION"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    CODING = "CODING"
    RECONCILIATION = "RECONCILIATION"
    FRAUD_CHECK = "FRAUD_CHECK"
    DECISION = "DECISION"
    HITL_REVIEW = "HITL_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentContext(DomainModel):
    trace_id: UUID = Field(default_factory=new_id)
    correlation_id: UUID = Field(default_factory=new_id)
    workflow_id: UUID = Field(default_factory=new_id)
    claim_id: UUID | None = None
    document_id: UUID | None = None
    current_state: WorkflowState = WorkflowState.INGESTED
    results: dict[str, Any] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"
    updated_at: datetime = Field(default_factory=utcnow)

    def get_result(self, agent_name: str, default: Any = None) -> Any:
        return self.results.get(agent_name, default)


    def set_result(self, agent_name: str, value: Any) -> None:
        self.results[agent_name] = value
        self.updated_at = utcnow()

    def set_error(self, agent_name: str, error: str) -> None:
        self.errors[agent_name] = error
        self.updated_at = utcnow()
