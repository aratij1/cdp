"""Blind review assignment, disagreement detection, and governed truth resolution."""
from __future__ import annotations

import hashlib
from collections import defaultdict

from evaluation.routing.label_quality import agreement_from_label_pairs
from packages.document_taxonomy.taxonomy import DocumentClass

from .contracts import (
    AdjudicationRecord,
    BlindReviewRecord,
    CorpusAssetIntakeRecord,
    ReviewStatus,
)

HARD_CONFUSER_SUBTYPES = {
    DocumentClass.CUSTOM_PROFESSIONAL,
    DocumentClass.CUSTOM_INSTITUTIONAL,
    DocumentClass.EOB,
    DocumentClass.ITEMIZED_BILL,
    DocumentClass.MEDICAL_INVOICE,
}


def requires_double_review(record: CorpusAssetIntakeRecord, minimum_rate: float = .20) -> bool:
    """Confusers are always doubled; remaining assets use a stable blinded sample."""
    if record.truth_subtype in HARD_CONFUSER_SUBTYPES:
        return True
    bucket = int(hashlib.sha256(record.asset_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < minimum_rate


def create_blind_assignments(
    records: tuple[CorpusAssetIntakeRecord, ...], reviewer_ids: tuple[str, ...]
) -> list[dict]:
    if records and not reviewer_ids:
        raise ValueError("AT_LEAST_ONE_REVIEWER_REQUIRED")
    if any(requires_double_review(record) for record in records) and len(set(reviewer_ids)) < 2:
        raise ValueError("TWO_INDEPENDENT_REVIEWERS_REQUIRED")
    assignments = []
    for index, record in enumerate(sorted(records, key=lambda item: item.asset_id)):
        primary = reviewer_ids[index % len(reviewer_ids)]
        assignments.append({"asset_id": record.asset_id, "reviewer_id": primary,
                            "review_role": "REVIEWER_1", "labels_visible": False})
        if requires_double_review(record):
            secondary = next(item for item in reviewer_ids if item != primary)
            assignments.append({"asset_id": record.asset_id, "reviewer_id": secondary,
                                "review_role": "REVIEWER_2", "labels_visible": False})
    return assignments


def _disagreement_codes(left: BlindReviewRecord, right: BlindReviewRecord) -> tuple[str, ...]:
    dimensions = {
        "TOP_LEVEL_DISAGREEMENT": left.top_level_label != right.top_level_label,
        "STANDARD_STATUS_DISAGREEMENT": left.standard_status != right.standard_status,
        "STANDARD_FAMILY_DISAGREEMENT": left.standard_family != right.standard_family,
        "SUBTYPE_DISAGREEMENT": left.subtype != right.subtype,
        "PROCESSING_ROUTE_DISAGREEMENT": left.expected_processing_route != right.expected_processing_route,
        "AMBIGUITY_DISAGREEMENT": left.ambiguity != right.ambiguity,
    }
    return tuple(code for code, present in dimensions.items() if present)


def resolve_reviews(
    assets: tuple[CorpusAssetIntakeRecord, ...],
    reviews: tuple[BlindReviewRecord, ...],
    adjudications: tuple[AdjudicationRecord, ...],
) -> tuple[dict[str, dict], dict]:
    by_asset: dict[str, list[BlindReviewRecord]] = defaultdict(list)
    for review in reviews:
        by_asset[review.asset_id].append(review)
    adjudication_by_asset = {item.asset_id: item for item in adjudications}
    resolutions: dict[str, dict] = {}
    agreement_pairs = []
    for asset in assets:
        asset_reviews = sorted(by_asset.get(asset.asset_id, []), key=lambda item: item.created_at)
        reasons: list[str] = []
        final_label = None
        status = ReviewStatus.PENDING
        if not asset_reviews:
            reasons.append("REVIEWER_1_MISSING")
        elif len(asset_reviews) > 2:
            reasons.append("TOO_MANY_REVIEWS")
        elif len({item.reviewer_id for item in asset_reviews}) != len(asset_reviews):
            reasons.append("REVIEWERS_NOT_INDEPENDENT")
        elif len({item.review_session_id for item in asset_reviews}) != len(asset_reviews):
            reasons.append("REVIEW_SESSIONS_NOT_INDEPENDENT")
        elif len(asset_reviews) == 1:
            if requires_double_review(asset):
                reasons.append("REVIEWER_2_MISSING")
                status = ReviewStatus.REVIEWER_1_COMPLETE
            elif asset_reviews[0].ambiguity:
                reasons.append("AMBIGUOUS_REVIEW_REQUIRES_ADJUDICATION")
                status = ReviewStatus.PENDING_ADJUDICATION
            else:
                final_label = asset_reviews[0].label()
                status = ReviewStatus.REVIEWER_1_COMPLETE
        else:
            left, right = asset_reviews
            agreement_pairs.append((left.label(), right.label()))
            disagreement_codes = _disagreement_codes(left, right)
            if disagreement_codes or left.ambiguity or right.ambiguity:
                reasons.extend(disagreement_codes or ("AMBIGUOUS_REVIEW_REQUIRES_ADJUDICATION",))
                status = ReviewStatus.PENDING_ADJUDICATION
            else:
                final_label = left.label()
                status = ReviewStatus.DOUBLE_REVIEW_COMPLETE
        adjudication = adjudication_by_asset.get(asset.asset_id)
        if status == ReviewStatus.PENDING_ADJUDICATION and adjudication is not None:
            final_label = adjudication.final_label
            status = ReviewStatus.ADJUDICATED
            reasons = []
        if final_label is not None and final_label != asset.declared_label():
            reasons.append("DECLARED_TRUTH_REVIEW_MISMATCH")
            final_label = None
        resolutions[asset.asset_id] = {
            "review_status": status.value,
            "review_count": len(asset_reviews),
            "double_review_required": requires_double_review(asset),
            "resolved": final_label is not None,
            "reason_codes": sorted(set(reasons)),
            "final_label": final_label.model_dump(mode="json") if final_label else None,
        }
    agreement_report = agreement_from_label_pairs(agreement_pairs)
    agreement_report["eligible_review_count"] = len(reviews)
    agreement_report["unresolved_critical_disagreements"] = sum(
        item["review_status"] == ReviewStatus.PENDING_ADJUDICATION for item in resolutions.values()
    )
    return resolutions, agreement_report
