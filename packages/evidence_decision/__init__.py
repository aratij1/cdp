"""Canonical field-decision service shared by runtime and evaluation."""

from packages.evidence_decision.contracts import (
    DecisionContext, FieldDecision, FieldDisposition, NextAction, ReferenceEvidence,
)
from packages.evidence_decision.service import EvidenceDecisionService

__all__ = [
    "DecisionContext", "EvidenceDecisionService", "FieldDecision",
    "FieldDisposition", "NextAction", "ReferenceEvidence",
]
