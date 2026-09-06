"""CDP 2.0 claim-intelligence shadow architecture.

This package is intentionally shadow-only. It does not replace the governed
production decision path or relax any acceptance policy.
"""

from .consistency import ClaimConsistencyEngine, ConsistencyResult
from .models import (
    AuthorityState,
    Candidate,
    CandidateEvidence,
    ClaimGraph,
    ExtractionState,
    FieldNode,
    ServiceLine,
)
from .risk import RiskDecision, RiskScorer
from .shadow import CDP2ShadowEngine, ShadowClaimResult

__all__ = [
    "AuthorityState",
    "CDP2ShadowEngine",
    "Candidate",
    "CandidateEvidence",
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

# Public shadow integration boundary. Importing it does not activate a pipeline.
from .document import DocumentPage, Token
from .models import EvidenceFeatures
from .pipeline import CDP2ShadowPipeline, LegacyResult, ShadowComparison, run_after_legacy

__all__ += [
    "CDP2ShadowPipeline",
    "DocumentPage",
    "EvidenceFeatures",
    "LegacyResult",
    "ShadowComparison",
    "Token",
    "run_after_legacy",
]
