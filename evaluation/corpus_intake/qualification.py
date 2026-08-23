"""Phase 7A.12 source, leakage, coverage, and per-asset qualification gates."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

from packages.document_taxonomy.corpus_v1 import PhiStatus, UsageStatus
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.storage.hashing import hamming_distance

from .contracts import (
    CorpusAssetIntakeRecord,
    QualificationStatus,
    SourceLineageAttestation,
)

APPROVED_PHI = {
    PhiStatus.PHI_FREE,
    PhiStatus.APPROVED_DEIDENTIFIED,
    PhiStatus.AUTHORIZED_CONTROLLED_TEST_DATA,
}
APPROVED_USAGE = {
    UsageStatus.AUTHORIZED,
    UsageStatus.PUBLICLY_USABLE,
    UsageStatus.INTERNAL_APPROVED,
    UsageStatus.LICENSED_FOR_EVALUATION,
}
HARD_NEGATIVES = {
    DocumentClass.CUSTOM_PROFESSIONAL,
    DocumentClass.CUSTOM_INSTITUTIONAL,
    DocumentClass.EOB,
    DocumentClass.ITEMIZED_BILL,
    DocumentClass.MEDICAL_INVOICE,
}
SUPPORT_NONCLAIM_UNKNOWN = {
    DocumentClass.CLAIM_SUPPORT,
    DocumentClass.NON_CLAIM,
    DocumentClass.UNKNOWN,
}


def source_hash_manifest(records: list[CorpusAssetIntakeRecord]) -> str:
    hashes = sorted(record.asset_sha256 for record in records)
    return hashlib.sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest()


def assess_source_attestations(
    assets: tuple[CorpusAssetIntakeRecord, ...],
    attestations: tuple[SourceLineageAttestation, ...],
) -> dict[str, dict]:
    assets_by_source: dict[str, list[CorpusAssetIntakeRecord]] = defaultdict(list)
    for asset in assets:
        assets_by_source[asset.source_family_id].append(asset)
    by_source = {item.source_family_id: item for item in attestations}
    results: dict[str, dict] = {}
    for source_id, source_assets in assets_by_source.items():
        attestation = by_source.get(source_id)
        reasons: list[str] = []
        if attestation is None:
            reasons.append("SOURCE_ATTESTATION_MISSING")
        else:
            if not attestation.qualified:
                reasons.append("SOURCE_ATTESTATION_NOT_PASS")
            if source_hash_manifest(source_assets) != attestation.source_hash_manifest:
                reasons.append("SOURCE_HASH_MANIFEST_MISMATCH")
            for asset in source_assets:
                if asset.acquisition_method != attestation.acquisition_method:
                    reasons.append("ACQUISITION_METHOD_LINEAGE_MISMATCH")
                if asset.template_lineage_id != attestation.template_lineage_id:
                    reasons.append("TEMPLATE_LINEAGE_MISMATCH")
                if asset.renderer_lineage_id != attestation.renderer_lineage_id:
                    reasons.append("RENDERER_LINEAGE_MISMATCH")
        results[source_id] = {
            "source_family_id": source_id,
            "asset_count": len(source_assets),
            "status": "PASS" if not reasons else "FAIL",
            "reason_codes": sorted(set(reasons)),
            "independence_status": attestation.independence_status.value if attestation else None,
        }
    for source_id in sorted(set(by_source) - set(assets_by_source)):
        results[source_id] = {
            "source_family_id": source_id,
            "asset_count": 0,
            "status": "FAIL",
            "reason_codes": ["ATTESTATION_HAS_NO_ASSETS"],
            "independence_status": by_source[source_id].independence_status.value,
        }
    return results


def audit_leakage(assets: tuple[CorpusAssetIntakeRecord, ...]) -> dict:
    exact_groups: dict[str, list[str]] = defaultdict(list)
    for asset in assets:
        exact_groups[asset.asset_sha256].append(asset.asset_id)
    exact_duplicates = {
        digest: sorted(ids) for digest, ids in exact_groups.items() if len(ids) > 1
    }
    related_cross_source = []
    near_duplicates = []
    lineage_fields = (
        "source_instance_id",
        "template_lineage_id",
        "renderer_lineage_id",
    )
    for index, left in enumerate(assets):
        for right in assets[index + 1 :]:
            distance = hamming_distance(left.perceptual_hash, right.perceptual_hash)
            if distance <= 4:
                near_duplicates.append(
                    {"left": left.asset_id, "right": right.asset_id, "hamming_distance": distance}
                )
            shared = [field for field in lineage_fields if getattr(left, field) == getattr(right, field)]
            if left.source_family_id != right.source_family_id and shared:
                related_cross_source.append(
                    {"left": left.asset_id, "right": right.asset_id,
                     "shared_lineage_fields": sorted(shared)}
                )
    blocked_assets = {
        asset_id for ids in exact_duplicates.values() for asset_id in ids
    }
    for pair in related_cross_source:
        blocked_assets.update((pair["left"], pair["right"]))
    for pair in near_duplicates:
        left = next(item for item in assets if item.asset_id == pair["left"])
        right = next(item for item in assets if item.asset_id == pair["right"])
        if left.source_family_id != right.source_family_id:
            blocked_assets.update((left.asset_id, right.asset_id))
            pair["cross_source_leak"] = True
        else:
            pair["cross_source_leak"] = False
    split_groups = {
        asset.asset_id: (
            f"{asset.source_family_id}|{asset.source_instance_id}|{asset.renderer_lineage_id}|"
            f"{asset.template_lineage_id}|{asset.degradation_family}"
        )
        for asset in assets
    }
    return {
        "exact_duplicate_groups": exact_duplicates,
        "near_duplicate_pairs": near_duplicates,
        "related_lineage_cross_source_pairs": related_cross_source,
        "blocked_asset_ids": sorted(blocked_assets),
        "split_group_by_asset": split_groups,
        "exact_duplicate_leakage_count": len(exact_duplicates),
        "cross_split_lineage_leakage_count": len(related_cross_source)
        + sum(bool(pair.get("cross_source_leak")) for pair in near_duplicates),
    }


def _pending_status(reasons: list[str]) -> QualificationStatus:
    if any(reason.startswith("PHI_") for reason in reasons):
        return QualificationStatus.PENDING_PHI_CLEARANCE
    if any("USAGE" in reason or "AUTHORIZATION" in reason for reason in reasons):
        return QualificationStatus.PENDING_AUTHORIZATION
    if any("ATTESTATION" in reason or "LINEAGE" in reason or "MANIFEST" in reason for reason in reasons):
        return QualificationStatus.PENDING_ATTESTATION
    if any("ADJUDICATION" in reason or "DISAGREEMENT" in reason for reason in reasons):
        return QualificationStatus.PENDING_ADJUDICATION
    return QualificationStatus.PENDING_REVIEW


def qualify_assets(
    assets: tuple[CorpusAssetIntakeRecord, ...],
    integrity: dict[str, dict],
    source_results: dict[str, dict],
    review_results: dict[str, dict],
    leakage: dict,
) -> dict[str, dict]:
    blocked = set(leakage["blocked_asset_ids"])
    results = {}
    for asset in assets:
        exclusion_reasons: list[str] = []
        pending_reasons: list[str] = []
        evidence = integrity.get(asset.asset_id)
        if evidence is None:
            exclusion_reasons.append("ASSET_INTEGRITY_NOT_RUN")
        elif not evidence["integrity_passed"]:
            exclusion_reasons.extend(evidence["reason_codes"])
        if not asset.split_eligibility:
            exclusion_reasons.append("SPLIT_INELIGIBLE")
        if asset.asset_id in blocked:
            exclusion_reasons.append("DUPLICATE_OR_CROSS_SOURCE_LINEAGE_LEAK")
        if asset.phi_status not in APPROVED_PHI:
            pending_reasons.append("PHI_CLEARANCE_REQUIRED")
        if asset.usage_status == UsageStatus.RESTRICTED:
            exclusion_reasons.append("USAGE_RESTRICTED")
        elif asset.usage_status not in APPROVED_USAGE:
            pending_reasons.append("USAGE_AUTHORIZATION_REQUIRED")
        source = source_results.get(asset.source_family_id)
        if source is None or source["status"] != "PASS":
            pending_reasons.extend((source or {}).get("reason_codes", ["SOURCE_ATTESTATION_MISSING"]))
        review = review_results.get(asset.asset_id)
        if review is None or not review["resolved"]:
            pending_reasons.extend((review or {}).get("reason_codes", ["REVIEWER_1_MISSING"]))
        if exclusion_reasons:
            status = QualificationStatus.EXCLUDED
            reasons = exclusion_reasons + pending_reasons
        elif pending_reasons:
            status = _pending_status(pending_reasons)
            reasons = pending_reasons
        else:
            status = QualificationStatus.QUALIFIED
            reasons = []
        results[asset.asset_id] = {
            "asset_id": asset.asset_id,
            "qualification_status": status.value,
            "reason_codes": sorted(set(reasons)),
            "source_family_id": asset.source_family_id,
            "truth_top_level_class": asset.truth_top_level_class.value,
            "truth_subtype": asset.truth_subtype.value,
            "expected_processing_route": asset.expected_processing_route.value,
            "split_group_id": leakage["split_group_by_asset"][asset.asset_id],
        }
    return results


def record_residual_leakage(leakage: dict, asset_results: dict[str, dict]) -> dict:
    """Record leakage in the eligible corpus after detected assets are excluded."""
    qualified_ids = {
        asset_id for asset_id, item in asset_results.items()
        if item["qualification_status"] == QualificationStatus.QUALIFIED
    }
    residual_exact = sum(
        len(qualified_ids.intersection(asset_ids)) > 1
        for asset_ids in leakage["exact_duplicate_groups"].values()
    )
    residual_cross = sum(
        pair["left"] in qualified_ids and pair["right"] in qualified_ids
        for pair in leakage["related_lineage_cross_source_pairs"]
    ) + sum(
        bool(pair.get("cross_source_leak"))
        and pair["left"] in qualified_ids and pair["right"] in qualified_ids
        for pair in leakage["near_duplicate_pairs"]
    )
    leakage["residual_exact_duplicate_leakage_count"] = residual_exact
    leakage["residual_cross_split_lineage_leakage_count"] = residual_cross
    return leakage


def coverage_report(
    assets: tuple[CorpusAssetIntakeRecord, ...], asset_results: dict[str, dict]
) -> dict:
    qualified = [
        asset for asset in assets
        if asset_results[asset.asset_id]["qualification_status"] == QualificationStatus.QUALIFIED
    ]
    subtype_counts = Counter(asset.truth_subtype.value for asset in qualified)
    top_counts = Counter(asset.truth_top_level_class.value for asset in qualified)
    sources_by_subtype: dict[str, set[str]] = defaultdict(set)
    source_counts_by_subtype: dict[str, Counter] = defaultdict(Counter)
    for asset in qualified:
        sources_by_subtype[asset.truth_subtype.value].add(asset.source_family_id)
        source_counts_by_subtype[asset.truth_subtype.value][asset.source_family_id] += 1
    concentration = {}
    concentration_failures = []
    for subtype, counts in source_counts_by_subtype.items():
        total = sum(counts.values())
        maximum = max(counts.values()) / total if total else 0.0
        concentration[subtype] = {
            "largest_source_fraction": maximum,
            "source_count": len(counts),
            "counts": dict(sorted(counts.items())),
        }
        if total >= 20 and len(counts) > 1 and maximum > .70:
            concentration_failures.append(subtype)
    hard_negative_count = sum(subtype_counts[item.value] for item in HARD_NEGATIVES)
    support_nonclaim_unknown_count = sum(
        top_counts[item.value] for item in SUPPORT_NONCLAIM_UNKNOWN
    )
    family_source_matrix = {
        subtype: dict(sorted(counts.items()))
        for subtype, counts in sorted(source_counts_by_subtype.items())
    }
    return {
        "qualified_pages": len(qualified),
        "independent_sources": len({item.source_family_id for item in qualified}),
        "qualified_source_ids": sorted({item.source_family_id for item in qualified}),
        "subtype_counts": dict(sorted(subtype_counts.items())),
        "top_level_counts": dict(sorted(top_counts.items())),
        "sources_per_subtype": {
            key: len(value) for key, value in sorted(sources_by_subtype.items())
        },
        "hard_negative_count": hard_negative_count,
        "support_nonclaim_unknown_count": support_nonclaim_unknown_count,
        "source_concentration": concentration,
        "source_concentration_failures": sorted(concentration_failures),
        "family_source_matrix": family_source_matrix,
    }


def qualification_gate(
    assets: tuple[CorpusAssetIntakeRecord, ...],
    asset_results: dict[str, dict],
    source_results: dict[str, dict],
    review_agreement: dict,
    leakage: dict,
    coverage: dict,
) -> dict:
    counts = Counter(item["qualification_status"] for item in asset_results.values())
    review_relevant_statuses = {
        QualificationStatus.QUALIFIED.value,
        QualificationStatus.PENDING_REVIEW.value,
        QualificationStatus.PENDING_ADJUDICATION.value,
    }
    review_relevant = [
        item for item in asset_results.values()
        if item["qualification_status"] in review_relevant_statuses
    ]
    resolved = sum(
        review_agreement.get("asset_resolutions", {}).get(item["asset_id"], {}).get("resolved", False)
        for item in review_relevant
    )
    double_reviewed = review_agreement.get("double_reviewed_pages", 0)
    review_coverage = resolved / len(review_relevant) if review_relevant else 0.0
    double_review_rate = double_reviewed / len(review_relevant) if review_relevant else 0.0
    qualified_sources = set(coverage["qualified_source_ids"])
    checks = {
        "minimum_qualified_pages": coverage["qualified_pages"] >= 500,
        "minimum_independent_sources": coverage["independent_sources"] >= 4,
        "cms_pages": coverage["subtype_counts"].get("CMS1500", 0) >= 100,
        "cms_sources": coverage["sources_per_subtype"].get("CMS1500", 0) >= 3,
        "ub_pages": coverage["subtype_counts"].get("UB04", 0) >= 100,
        "ub_sources": coverage["sources_per_subtype"].get("UB04", 0) >= 3,
        "hard_negatives": coverage["hard_negative_count"] >= 100,
        "support_nonclaim_unknown": coverage["support_nonclaim_unknown_count"] >= 100,
        "source_concentration": not coverage["source_concentration_failures"],
        "all_source_attestations_pass": bool(qualified_sources)
        and all(source_results[source]["status"] == "PASS" for source in qualified_sources),
        "review_coverage": bool(review_relevant) and review_coverage == 1.0,
        "double_review_rate": double_review_rate >= .15,
        "unresolved_critical_disagreements": review_agreement.get(
            "unresolved_critical_disagreements", 0
        ) == 0,
        "exact_duplicate_leakage": leakage.get(
            "residual_exact_duplicate_leakage_count", leakage["exact_duplicate_leakage_count"]
        ) == 0,
        "cross_split_lineage_leakage": leakage.get(
            "residual_cross_split_lineage_leakage_count",
            leakage["cross_split_lineage_leakage_count"],
        ) == 0,
        "no_pending_assets": bool(assets) and (
            counts[QualificationStatus.QUALIFIED.value] + counts[QualificationStatus.EXCLUDED.value]
        ) == len(assets),
    }
    passed = all(checks.values())
    mature = passed and coverage["qualified_pages"] >= 1000
    return {
        "gate": "PHASE_7A_12_QUALIFIED_CORPUS",
        "checks": checks,
        "input_assets": len(assets),
        "qualified": counts[QualificationStatus.QUALIFIED.value],
        "excluded": counts[QualificationStatus.EXCLUDED.value],
        "pending": len(assets) - counts[QualificationStatus.QUALIFIED.value]
        - counts[QualificationStatus.EXCLUDED.value],
        "status_counts": dict(sorted(counts.items())),
        "review_coverage": review_coverage,
        "double_review_rate": double_review_rate,
        "qualification_level": "MATURE" if mature else "MILESTONE_A_PROVISIONAL" if passed else None,
        "corpus_status": "QUALIFIED" if mature else "PROVISIONAL_QUALIFIED" if passed else "NEEDS_MORE_DATA",
        "freeze_allowed": passed,
        "provisional_loso_allowed": passed,
        "loso_allowed": passed,
        "blocking_reasons": sorted(name for name, passed_check in checks.items() if not passed_check),
    }
