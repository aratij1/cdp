"""Human/SME distinguishability protocol; criteria are data, not learned features."""
from packages.domain.common import DomainModel
from .taxonomy import DocumentClass


class ClassDefinition(DomainModel):
    label: DocumentClass
    business_definition: str
    required_semantic_traits: tuple[str, ...]
    exclusion_traits: tuple[str, ...]
    hard_confusers: tuple[DocumentClass, ...]


class DistinguishabilityObservation(DomainModel):
    document_id: str
    reviewer_id: str
    label: DocumentClass
    independently_assignable: bool
    ambiguous_with: tuple[DocumentClass, ...] = ()
    reason_codes: tuple[str, ...] = ()


def pairwise_agreement(observations: tuple[DistinguishabilityObservation, ...]) -> float:
    by_document: dict[str, list[DocumentClass]] = {}
    for observation in observations:
        by_document.setdefault(observation.document_id, []).append(observation.label)
    pairs = agreements = 0
    for labels in by_document.values():
        for index, left in enumerate(labels):
            for right in labels[index + 1:]:
                pairs += 1
                agreements += left == right
    return agreements / pairs if pairs else 0.0
