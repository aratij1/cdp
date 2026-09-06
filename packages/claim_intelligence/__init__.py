"""CDP 2.0 claim-intelligence shadow architecture.

This package is intentionally shadow-only. It does not replace the governed
production decision path or relax any acceptance policy.
"""

from .models import (
    AuthorityState,
    Candidate,
    CandidateEvidence,
    ClaimGraph,
    ExtractionState,
    FieldNode,
    ServiceLine,
)
from .consistency import ClaimConsistencyEngine, ConsistencyResult
from .risk import RiskDecision, RiskScorer
from .shadow import CDP2ShadowEngine, ShadowClaimResult

__all__ = [
    "AuthorityState",
    "Candidate",
    "CandidateEvidence",
    "CDP2ShadowEngine",
    "ClaimConsistencyEngine",
    "ClaimGraph",
    "ConsistencyResult",
    "ExtractionState",
    "FieldNode",
    "RiskDecision",
    "RiskScorer",
    "ServiceLine",
    "ShadowClaimResult",
]
