"""Typed contracts for adaptive, field-level escalation decisions."""
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

class PolicyAction(StrEnum):
    ACCEPT="ACCEPT"; EXPAND_CROP="EXPAND_CROP"; RETRY_PREPROCESSING="RETRY_PREPROCESSING"
    RAPIDOCR="RAPIDOCR"; PADDLEOCR="PADDLEOCR"; TESSERACT="TESSERACT"
    REFERENCE_LOOKUP="REFERENCE_LOOKUP"; DOCLING="DOCLING"; TEXTRACT="TEXTRACT"
    GEMINI_CHEAP="GEMINI_CHEAP"; GEMINI_STANDARD="GEMINI_STANDARD"; GEMINI_ADVANCED="GEMINI_ADVANCED"
    HITL="HITL"; ABSTAIN="ABSTAIN"

class CandidateSummary(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source: str; value: str|None=None; confidence: float=Field(default=0, ge=0, le=1)

class DecisionContext(BaseModel):
    model_config=ConfigDict(extra="forbid")
    document_type: str; field_name: str; criticality: str
    image_quality: float=Field(default=1, ge=0, le=1)
    registration_confidence: float=Field(default=1, ge=0, le=1)
    candidates: list[CandidateSummary]=Field(default_factory=list)
    validation_results: dict[str,bool]=Field(default_factory=dict)
    reference_results: dict[str,bool]=Field(default_factory=dict)
    previous_attempts: set[PolicyAction]=Field(default_factory=set)
    current_confidence: float=Field(default=0, ge=0, le=1)
    remaining_sla: float=Field(default=float("inf"), ge=0)
    remaining_budget: float=Field(default=float("inf"), ge=0)
    evidence_policy_satisfied: bool=False; unresolved_contradiction: bool=False
    reference_available: bool=False; cloud_processing_allowed: bool=False; is_table_field: bool=False

class PolicyDecision(BaseModel):
    model_config=ConfigDict(extra="forbid")
    action: PolicyAction; reason_codes: list[str]; estimated_cost_usd: float=Field(ge=0)
    estimated_latency_seconds: float=Field(ge=0); route: str
