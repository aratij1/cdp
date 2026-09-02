from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4
from typing import Any, Dict, Optional
from pydantic import Field
from packages.domain.common import DomainModel, utcnow, new_id
from enum import StrEnum


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
    claim_id: Optional[UUID] = None
    document_id: Optional[UUID] = None
    current_state: WorkflowState = WorkflowState.INGESTED
    results: Dict[str, Any] = Field(default_factory=dict)
    errors: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
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
