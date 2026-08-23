"""Fail-closed Phase 7A.11 corpus qualification and duplicate/lineage audit."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from packages.document_taxonomy.corpus_v1 import QualifiedRoutingCorpusManifest

PRIORITY = {"CMS1500", "UB04", "CUSTOM_PROFESSIONAL", "CUSTOM_INSTITUTIONAL",
            "EOB", "ITEMIZED_BILL", "MEDICAL_INVOICE", "OTHER_ATTACHMENT", "OTHER_NON_CLAIM"}


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def qualify(manifest: QualifiedRoutingCorpusManifest) -> dict:
    source_by_id = {source.source_family_id: source for source in manifest.sources}
    exclusions: dict[str, list[str]] = defaultdict(list)
    exact: dict[str, list[str]] = defaultdict(list)
    layout: dict[str, list[str]] = defaultdict(list)
    for page in manifest.pages:
        exact[page.file_sha256].append(page.page_id)
        layout[page.layout_fingerprint].append(page.page_id)
        source = source_by_id.get(page.source_family)
        if source is None or not source.qualified:
            exclusions[page.page_id].append("SOURCE_LINEAGE_NOT_INDEPENDENT_OR_UNQUALIFIED")
        if page.phi_status.value not in {"PHI_FREE", "APPROVED_DEIDENTIFIED"}:
            exclusions[page.page_id].append("PHI_GATE_FAILED")
        if page.license_or_usage_status.value not in {"AUTHORIZED", "PUBLICLY_USABLE", "INTERNAL_APPROVED"}:
            exclusions[page.page_id].append("USAGE_GATE_FAILED")
        if not page.image_readable:
            exclusions[page.page_id].append("IMAGE_UNREADABLE")
        if not page.split_eligibility:
            exclusions[page.page_id].append("SPLIT_INELIGIBLE")
    exact_duplicates = {digest: ids for digest, ids in exact.items() if len(ids) > 1}
    for ids in exact_duplicates.values():
        for page_id in ids:
            exclusions[page_id].append("EXACT_DUPLICATE")

    pages = list(manifest.pages)
    near_duplicates = []
    lineage_leaks = []
    for index, left in enumerate(pages):
        for right in pages[index + 1:]:
            if _hamming(left.perceptual_hash, right.perceptual_hash) <= 4:
                pair = {"left": left.page_id, "right": right.page_id,
                        "hamming": _hamming(left.perceptual_hash, right.perceptual_hash)}
                near_duplicates.append(pair)
                if left.base_asset_id != right.base_asset_id or left.source_family != right.source_family:
                    lineage_leaks.append({**pair, "reason": "NEAR_DUPLICATE_CROSSES_DECLARED_LINEAGE"})
            if (left.layout_fingerprint == right.layout_fingerprint
                    and (left.source_family != right.source_family
                         or left.template_lineage != right.template_lineage)):
                lineage_leaks.append({"left": left.page_id, "right": right.page_id,
                                      "reason": "LAYOUT_CLONE_CROSSES_DECLARED_LINEAGE"})
    for leak in lineage_leaks:
        exclusions[leak["left"]].append(leak["reason"])
        exclusions[leak["right"]].append(leak["reason"])

    reviewed = [page for page in pages if page.reviewer_2_label is not None]
    double_review_rate = len(reviewed) / len(pages) if pages else 0.0
    sources_per_class: dict[str, set[str]] = defaultdict(set)
    counts = Counter()
    for page in pages:
        counts[page.truth_subtype.value] += 1
        sources_per_class[page.truth_subtype.value].add(page.source_family)
    source_gaps = {label: len(sources_per_class[label]) for label in PRIORITY
                   if len(sources_per_class[label]) < manifest.minimum_sources_per_priority_class}
    hard_negative = {
        "CMS1500": sum(counts[name] for name in ("CUSTOM_PROFESSIONAL", "EOB", "ITEMIZED_BILL", "MEDICAL_INVOICE")),
        "UB04": sum(counts[name] for name in ("CUSTOM_INSTITUTIONAL", "EOB", "ITEMIZED_BILL", "MEDICAL_INVOICE")),
    }
    corpus_reasons = []
    if len(pages) < manifest.minimum_pages: corpus_reasons.append("MINIMUM_PAGE_COUNT_NOT_MET")
    if double_review_rate < manifest.double_review_minimum_rate: corpus_reasons.append("DOUBLE_REVIEW_RATE_NOT_MET")
    if source_gaps: corpus_reasons.append("PRIORITY_CLASS_SOURCE_DIVERSITY_NOT_MET")
    if len(source_by_id) < 4: corpus_reasons.append("MINIMUM_MEANINGFUL_SOURCE_FAMILIES_NOT_MET")
    if not all(hard_negative.values()): corpus_reasons.append("MANDATORY_HARD_NEGATIVES_MISSING")
    if exclusions: corpus_reasons.append("PAGE_QUALITY_EXCLUSIONS_PRESENT")
    qualified = not corpus_reasons
    return {"corpus_version": manifest.corpus_version, "page_count": len(pages),
            "qualified_page_count": len(pages) - len(exclusions), "class_counts": dict(counts),
            "source_count": len(source_by_id), "sources_per_priority_class":
            {label: len(sources_per_class[label]) for label in sorted(PRIORITY)},
            "source_gaps": source_gaps, "double_review_rate": double_review_rate,
            "hard_negative_counts": hard_negative, "exact_duplicates": exact_duplicates,
            "near_duplicates": near_duplicates, "layout_groups":
            {fingerprint: ids for fingerprint, ids in layout.items() if len(ids) > 1},
            "lineage_leaks": lineage_leaks, "page_exclusions": dict(exclusions),
            "corpus_reasons": corpus_reasons, "qualified": qualified,
            "loso_allowed": qualified, "freeze_allowed": qualified}


def write_reports(report: dict, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2), "utf-8")
    markdown_path.write_text(
        "# Routing Corpus Duplicate and Qualification Report\n\n"
        f"Status: **{'PASS' if report['qualified'] else 'FAIL'}**\n\n"
        f"Pages: {report['page_count']}; qualified: {report['qualified_page_count']}; "
        f"sources: {report['source_count']}; double review: {report['double_review_rate']:.2%}.\n\n"
        f"Exact duplicate groups: {len(report['exact_duplicates'])}; near-duplicate pairs: "
        f"{len(report['near_duplicates'])}; lineage leaks: {len(report['lineage_leaks'])}.\n\n"
        f"Blocking reasons: {', '.join(report['corpus_reasons']) or 'none'}.\n", "utf-8")
