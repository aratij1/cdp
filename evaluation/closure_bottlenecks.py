"""Candidate recall diagnostics with explicit, non-promotable truth scopes."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from packages.claim_intelligence.document import fingerprint
from packages.claim_intelligence.normalization import normalize

RELEASE_AUTHORITIES = frozenset(
    {"TRUSTED_HUMAN", "ADJUDICATED", "DUAL_REVIEW_AGREED", "AUTHORITATIVE_SOURCE"}
)
ENGINEERING_AUTHORITIES = frozenset({"FROZEN_REGRESSION", "SYNTHETIC_KNOWN_SOURCE"})
BUCKETS = (
    "TRUTH_NOT_IN_CANDIDATES",
    "TRUTH_IN_CANDIDATES_WRONG_RANK",
    "TRUTH_TOP1_BUT_REJECTED",
    "TRUTH_TOP1_AUTHORITY_BLOCKED",
    "TRUTH_TOP1_EXTERNAL_EVIDENCE_BLOCKED",
    "REFERENCE_CONFLICT",
    "NOT_EVALUABLE",
    "CORRECT_ACCEPTED",
)


def decompose(rows: list[dict[str, Any]], *, scope: str) -> dict[str, Any]:
    """Score ranked observations, never send reference values to extraction.

    Release rows additionally need audited source binding and a frozen truth hash.
    The output intentionally omits values, candidate strings, and source paths.
    """
    if scope not in {"ENGINEERING", "RELEASE"}:
        raise ValueError("INVALID_TRUTH_SCOPE")
    seen = set()
    records = []
    groups: dict[str, dict[str, list[dict]]] = {
        dimension: defaultdict(list)
        for dimension in ("field", "form", "quality", "criticality", "claim")
    }
    for row in rows:
        key = (row["claim_id"], row["field"])
        if key in seen:
            raise ValueError("DUPLICATE_FIELD_DENOMINATOR")
        seen.add(key)
        authority = row.get("authority", "UNLABELED")
        eligible = authority in (RELEASE_AUTHORITIES | ENGINEERING_AUTHORITIES)
        if scope == "RELEASE":
            eligible = (
                authority in RELEASE_AUTHORITIES
                and row.get("source_binding_verified") is True
                and bool(row.get("truth_sha256"))
            )
        reference = row.get("truth")
        eligible = eligible and isinstance(reference, str) and bool(reference.strip())
        candidates = row.get("candidates", [])
        ranked = [normalize(row["field"], v)[0] for v in candidates]
        expected = normalize(row["field"], str(reference))[0] if eligible else None
        rank = ranked.index(expected) + 1 if expected is not None and expected in ranked else None
        top = normalize(row["field"], row.get("top1") or "")[0]
        if not eligible:
            bucket = "NOT_EVALUABLE"
        elif row.get("reference_conflict"):
            bucket = "REFERENCE_CONFLICT"
        elif rank is None:
            bucket = "TRUTH_NOT_IN_CANDIDATES"
        elif top != expected:
            bucket = "TRUTH_IN_CANDIDATES_WRONG_RANK"
        elif row.get("authority_blocked"):
            bucket = "TRUTH_TOP1_AUTHORITY_BLOCKED"
        elif row.get("external_evidence_blocked"):
            bucket = "TRUTH_TOP1_EXTERNAL_EVIDENCE_BLOCKED"
        elif not row.get("accepted"):
            bucket = "TRUTH_TOP1_BUT_REJECTED"
        else:
            bucket = "CORRECT_ACCEPTED"
        record = {
            "claim": fingerprint(row["claim_id"]),
            "field": row["field"],
            "form": row.get("form", "UNKNOWN"),
            "quality": row.get("quality", "UNKNOWN"),
            "criticality": row.get("criticality", "UNKNOWN"),
            "authority": authority,
            "bucket": bucket,
            "evaluable": bool(eligible and not row.get("reference_conflict")),
            "reference_rank": rank,
            "candidate_count": len(candidates),
            "top1_correct": top == expected if eligible else None,
        }
        records.append(record)
        for dimension, collection in groups.items():
            collection[record[dimension]].append(record)

    def summarize(items: list[dict]) -> dict:
        measured = [r for r in items if r["evaluable"]]
        return {
            "fields": len(items),
            "evaluated_fields": len(measured),
            "buckets": {b: sum(r["bucket"] == b for r in items) for b in BUCKETS},
            "recall": {
                f"R@{k}": (
                    sum(
                        r["reference_rank"] is not None and r["reference_rank"] <= k
                        for r in measured
                    )
                    / len(measured)
                    if measured
                    else None
                )
                for k in (1, 3, 5)
            },
            "mean_candidates": sum(r["candidate_count"] for r in items) / len(items)
            if items
            else None,
            "over_five_candidates": sum(r["candidate_count"] > 5 for r in items),
        }

    return {
        "scope": scope,
        "release_qualification": scope == "RELEASE",
        "authority_distribution": dict(Counter(r["authority"] for r in records)),
        "summary": summarize(records),
        "by_dimension": {
            d: {k: summarize(v) for k, v in sorted(collection.items())}
            for d, collection in groups.items()
        },
        "fields": records,
        "cohort_sha256": fingerprint(sorted(seen)),
    }
