"""Reuse the governed independence predicate and add normalized pixel-region checks."""

from packages.claim_evidence.independence import observations_are_independent

from .models import Candidate, CandidateEvidence


def complete(item: CandidateEvidence) -> bool:
    return all(
        (item.source_id, item.page_id, item.crop_hash, item.localization_region, item.provenance_id)
    )


def independent(left: CandidateEvidence, right: CandidateEvidence) -> bool:
    if not complete(left) or not complete(right):
        return False
    if (left.source_id, left.page_id, left.localization_region) == (
        right.source_id,
        right.page_id,
        right.localization_region,
    ):
        return False
    if (
        left.bbox
        and left.bbox == right.bbox
        and (left.source_id, left.page_id) == (right.source_id, right.page_id)
    ):
        return False

    def mapping(item: CandidateEvidence) -> dict:
        return {
            "invocation_id": item.provenance_id,
            "crop_sha256": item.crop_hash,
            "localization_region_id": item.localization_region,
            "shared_dependency_ids": item.dependencies,
        }

    return observations_are_independent(mapping(left), mapping(right))


def corroborated(candidate: Candidate) -> bool:
    return any(
        independent(a, b)
        for i, a in enumerate(candidate.evidence)
        for b in candidate.evidence[i + 1 :]
    )


def corroborated_alternatives(candidate: Candidate, alternatives: list[Candidate]) -> bool:
    if corroborated(candidate):
        return True
    value = candidate.normalized_value or candidate.value
    return any(
        independent(a, b)
        for other in alternatives
        if other.candidate_id != candidate.candidate_id
        and (other.normalized_value or other.value) == value
        for a in candidate.evidence
        for b in other.evidence
    )
