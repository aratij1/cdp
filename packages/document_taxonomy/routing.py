"""Evaluation-only hierarchical routing contracts with explicit abstention."""
from pydantic import Field

from packages.domain.common import DomainModel
from .taxonomy import DocumentClass, DocumentTaxonomyV1


class HierarchicalRouteEvidence(DomainModel):
    taxonomy_version: str = DocumentTaxonomyV1.version
    evaluated_parent: DocumentClass
    proposed_child: DocumentClass
    confidence: float = Field(ge=0, le=1)
    evidence_codes: tuple[str, ...]
    source_component: str


class HierarchicalRouteObservation(DomainModel):
    taxonomy_version: str = DocumentTaxonomyV1.version
    path: tuple[DocumentClass, ...]
    terminal_label: DocumentClass
    abstained: bool
    reason_codes: tuple[str, ...]
    evaluation_only: bool = True


def assemble_observation(evidence: tuple[HierarchicalRouteEvidence, ...], threshold: float = .98) -> HierarchicalRouteObservation:
    current = DocumentClass.DOCUMENT
    path = [current]
    reasons = []
    while True:
        candidates = [item for item in evidence if item.evaluated_parent == current]
        if not candidates:
            return HierarchicalRouteObservation(path=tuple(path), terminal_label=DocumentClass.UNKNOWN,
                                                abstained=True, reason_codes=("MISSING_LEVEL_EVIDENCE",))
        candidate = max(candidates, key=lambda item: item.confidence)
        if candidate.proposed_child not in DocumentTaxonomyV1.children_of(current):
            raise ValueError("hierarchical evidence proposes a non-child class")
        if candidate.confidence < threshold:
            return HierarchicalRouteObservation(path=tuple(path), terminal_label=DocumentClass.UNKNOWN,
                                                abstained=True, reason_codes=("LEVEL_CONFIDENCE_BELOW_GATE",))
        current = candidate.proposed_child
        path.append(current)
        reasons.extend(candidate.evidence_codes)
        if not DocumentTaxonomyV1.children_of(current):
            return HierarchicalRouteObservation(path=tuple(path), terminal_label=current,
                                                abstained=False, reason_codes=tuple(reasons))
