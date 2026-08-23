"""Hierarchical reviewer agreement with raw agreement and Cohen's kappa."""
from __future__ import annotations

from collections import Counter

from packages.document_taxonomy.corpus_v1 import RoutingTaxonomyPageRecord
from packages.document_taxonomy.taxonomy import DocumentClass


def _kappa(left: list[str], right: list[str]) -> float | None:
    if not left: return None
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    lc, rc = Counter(left), Counter(right)
    expected = sum((lc[label] / len(left)) * (rc[label] / len(right)) for label in set(lc) | set(rc))
    return (observed - expected) / (1 - expected) if expected < 1 else (1.0 if observed == 1 else 0.0)


def _standard(label) -> str:
    return ("STANDARD" if label.subtype in {DocumentClass.CMS1500, DocumentClass.UB04}
            else "NON_STANDARD" if label.top_level_class == DocumentClass.CLAIM else "NOT_APPLICABLE")


def agreement_from_label_pairs(pairs: list[tuple[object, object]]) -> dict:
    """Calculate hierarchical agreement for an already-blinded review pair set."""
    dimensions = {
        "top_level": lambda label: label.top_level_class.value,
        "standard_non_standard": _standard,
        "cms_ub": lambda label: (label.subtype.value if label.subtype in
                                  {DocumentClass.CMS1500, DocumentClass.UB04} else "NOT_APPLICABLE"),
        "exact_subtype": lambda label: label.subtype.value,
        "processing_route": lambda label: label.expected_processing_route.value,
    }
    results = {}
    for name, accessor in dimensions.items():
        left = [accessor(pair[0]) for pair in pairs]
        right = [accessor(pair[1]) for pair in pairs]
        results[name] = {"reviewed": len(left),
                         "raw_agreement": sum(a == b for a, b in zip(left, right)) / len(left) if left else None,
                         "cohens_kappa": _kappa(left, right),
                         "disagreements": sum(a != b for a, b in zip(left, right))}
    return {"double_reviewed_pages": len(pairs), "dimensions": results,
            "taxonomy_collapse_recommended": []}


def agreement(pages: tuple[RoutingTaxonomyPageRecord, ...]) -> dict:
    reviewed = [page for page in pages if page.reviewer_2_label is not None]
    return agreement_from_label_pairs(
        [(page.reviewer_1_label, page.reviewer_2_label) for page in reviewed]
    )
