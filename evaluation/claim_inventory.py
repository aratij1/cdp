"""Build a PHI-safe claim inventory from explicit governed metadata, never adjacency."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from uuid import uuid4

from evaluation.qualification_state import mapped
from packages.real_data_evaluation.blind_workflow import FIELDS, content_digest
from packages.real_data_evaluation.qualification_jobs import publish as publish_immutable

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        return {"claims": None}
    return value if isinstance(value, dict) else {}


def _publish(path: Path, value: dict) -> None:
    if "evaluation_results" in path.parts: path = mapped(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _hash(value: str) -> str:
    return content_digest(value)


def _build_inventory(membership: dict, bindings: list[dict]) -> dict:
    """Measure membership readiness without requiring or constructing truth/predictions."""
    claims = membership.get("claims", {})
    if not isinstance(claims, dict) or any(
        not isinstance(k, str) or not k or not isinstance(v, dict) for k, v in claims.items()
    ):
        raise ValueError("MALFORMED_CLAIMS")
    claims = dict(claims)
    # Existing binding claim IDs are candidates only; a page list never proves completeness.
    for binding in bindings:
        claim_id = binding.get("claim_id")
        if isinstance(claim_id, str) and claim_id and claim_id not in claims:
            claims[claim_id] = {
                "package_id": binding.get("package_id"),
                "page_ids": [
                    b["source_page_id"] for b in bindings if b.get("claim_id") == claim_id
                ],
            }
    by_page: dict[str, list[dict]] = {}
    for binding in bindings:
        by_page.setdefault(binding.get("source_page_id", ""), []).append(binding)
    page_counts = Counter(p for row in claims.values() for p in row.get("page_ids", []))
    document_counts = Counter(d for row in claims.values() for d in row.get("documents", {}))
    governed = (
        membership.get("governed") is True
        and membership.get("complete_claim_membership_confirmed") is True
        and bool(membership.get("boundary_provenance"))
    )
    rows = []
    exact_pages: set[str] = set()
    reasons: Counter[str] = Counter()
    for claim_id, claim in sorted(claims.items()):
        issues = set()
        pages = claim.get("page_ids", [])
        package = claim.get("package_id")
        documents = claim.get("documents", {})
        forms = claim.get("claim_form_page_ids", [])
        attachments = claim.get("attachment_page_ids")
        if not governed:
            issues.add("GOVERNED_COMPLETE_MEMBERSHIP_REQUIRED")
        if not pages or not package:
            issues.add("CLAIM_SCOPE_REQUIRED")
        if any(page_counts[p] != 1 for p in pages):
            issues.add("AMBIGUOUS_PAGE_MEMBERSHIP")
        if any(document_counts[d] != 1 for d in documents):
            issues.add("AMBIGUOUS_DOCUMENT_MEMBERSHIP")
        if (
            not documents
            or Counter(p for doc in documents.values() for p in doc.get("page_ids", []))
            != Counter(pages)
            or any(
                not d.get("page_ids")
                or d.get("boundary") not in {"CONFIRMED", "GOVERNED"}
                or not d.get("boundary_provenance")
                for d in documents.values()
            )
        ):
            issues.add("CONFIRMED_DOCUMENT_BOUNDARIES_REQUIRED")
        if (
            not forms
            or attachments is None
            or Counter(forms + (attachments or [])) != Counter(pages)
        ):
            issues.add("COMPLETE_FORM_AND_ATTACHMENT_SCOPE_REQUIRED")
        expected = claim.get("expected_field_keys", [])
        valid_keys = all(
            isinstance(k, (list, tuple)) and len(k) == 2 and all(isinstance(v, str) for v in k)
            for k in expected
        )
        keys = {tuple(k) for k in expected} if valid_keys else set()
        if (
            not keys
            or len(keys) != len(expected)
            or not {(p, f) for p in forms for f in FIELDS} <= keys
            or any(p not in pages or not f for p, f in keys)
        ):
            issues.add("COMPLETE_EXPECTED_FIELDS_REQUIRED")
        for page in pages:
            matches = by_page.get(page, [])
            if len(matches) != 1:
                issues.add("AMBIGUOUS_SOURCE_BINDING" if matches else "SOURCE_BINDING_REQUIRED")
                continue
            b = matches[0]
            digest = b.get("rendered_page_sha256")
            if (
                b.get("state") != "EXACT"
                or not isinstance(digest, str)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or b.get("cdp_page_sha256") != digest
                or not b.get("cdp_page_id")
                or b.get("package_id") != package
                or b.get("claim_id") not in {None, claim_id}
            ):
                issues.add("EXACT_SOURCE_BINDING_REQUIRED")
        status = (
            "AMBIGUOUS"
            if any(i.startswith("AMBIGUOUS_") for i in issues)
            else "UNBOUND"
            if issues
            else "EXACT"
        )
        if status == "EXACT":
            exact_pages.update(pages)
        reasons.update(issues)
        rows.append(
            {
                "claim_id_sha256": _hash(claim_id),
                "package_id_sha256": _hash(package) if isinstance(package, str) else None,
                "page_ids_sha256": [_hash(p) for p in pages],
                "claim_form_page_ids_sha256": [_hash(p) for p in forms],
                "attachment_page_ids_sha256": [_hash(p) for p in attachments]
                if attachments is not None
                else None,
                "pages_per_claim": len(pages),
                "attachments_per_claim": len(attachments) if attachments is not None else None,
                "document_boundary_evidence_sha256": content_digest(documents)
                if documents
                else None,
                "membership_method": "EXPLICIT_GOVERNED_MANIFEST"
                if governed
                else "UNVERIFIED_METADATA",
                "membership_provenance_sha256": content_digest(
                    membership.get("boundary_provenance")
                )
                if governed
                else None,
                "membership_status": status,
                "issues": sorted(issues),
            }
        )
    if not rows:
        reasons["GOVERNED_COMPLETE_MEMBERSHIP_REQUIRED"] += 1
    states = Counter(row["membership_status"] for row in rows)
    return {
        "schema_version": 1,
        "status": "EXACT" if rows and states["EXACT"] == len(rows) else "EXTERNAL_INPUT_REQUIRED",
        "scope": "MEMBERSHIP_ONLY_NOT_TRUTH_OR_EXECUTION",
        "packages": len({b["package_id"] for b in bindings if b.get("package_id")}),
        "source_assets": len(
            {b["source_asset_sha256"] for b in bindings if b.get("source_asset_sha256")}
        ),
        "documents": len(document_counts),
        "claims_discovered": len(rows),
        "claims_exactly_bound": states["EXACT"],
        "claims_ambiguous": states["AMBIGUOUS"],
        "claims_unbound": states["UNBOUND"],
        "pages": len(by_page),
        "pages_exactly_claim_bound": len(exact_pages),
        "pages_without_exact_claim": len(set(by_page) - exact_pages),
        "claim_inventory_complete": governed and bool(rows) and states["EXACT"] == len(rows),
        "membership_inferred_from_adjacency": False,
        "identities_generated": False,
        "claims": rows,
        "issues": dict(sorted(reasons.items())),
    }


def build_inventory(membership: dict, bindings: list[dict]) -> dict:
    """Fail closed on malformed owner metadata without publishing source values."""
    try:
        result = _build_inventory(membership, bindings)
    except (TypeError, ValueError, KeyError, AttributeError):
        result = _build_inventory({}, [])
        result["issues"] = {"MALFORMED_MEMBERSHIP_OR_BINDINGS": 1}
    result["membership_ready"] = result["claim_inventory_complete"]
    return result


def build(root: Path = ROOT) -> dict:
    """Refresh inventory; materialize a complete explicit manifest without overwriting owner input."""
    private = root / "evaluation_results/qualification_closure"
    target = mapped(private / "claim_membership.local.json")
    bindings = _load(mapped(private / "source_page_bindings.local.json")).get("bindings", [])
    membership = _load(target)
    candidates = []
    # Only dedicated owner metadata inputs can become authority, never output reports.
    for name in (
        "package_manifest.local.json",
        "ingestion_lineage.local.json",
        "document_manifest.local.json",
    ):
        source = _load(private / name)
        if source and build_inventory(source, bindings)["claim_inventory_complete"]:
            candidates.append(source)
    distinct = {content_digest(source): source for source in candidates}
    if not target.exists() and len(distinct) == 1:
        membership = next(iter(distinct.values()))
        try:
            publish_immutable(target, membership)
        except ValueError:
            membership = _load(target)
    result = build_inventory(membership, bindings)
    result["governed_manifest_candidates"] = len(candidates)
    conflict = len(distinct) > 1 or bool(
        membership and distinct and content_digest(membership) not in distinct
    )
    result["conflicting_governed_manifests"] = conflict
    if conflict:
        result["membership_ready"] = False
        result["claim_inventory_complete"] = False
        result["status"] = "EXTERNAL_INPUT_REQUIRED"
        result["issues"]["CONFLICTING_GOVERNED_MANIFESTS"] = 1
        for row in result["claims"]:
            row["membership_status"] = "AMBIGUOUS"
            row["issues"].append("CONFLICTING_GOVERNED_MANIFESTS")
        result["claims_ambiguous"] = result["claims_discovered"]
        result["claims_exactly_bound"] = result["claims_unbound"] = 0
        result["pages_exactly_claim_bound"] = 0
        result["pages_without_exact_claim"] = result["pages"]
    result["membership_materialized"] = bool(membership)
    from evaluation.owner_sequence_membership import refresh as refresh_owner_membership

    owner_membership = refresh_owner_membership(root, bindings)
    if owner_membership:
        result["owner_confirmed_source_membership"] = owner_membership
        result["cohort_claim_inventory_scope"] = "FROZEN_REVIEW_COHORT_ONLY"
        result["source_groups"] = owner_membership.get("groups", {})
        result["source_inventory_totals"] = owner_membership.get("total", {})
    _publish(root / "evaluation_results/real_release/claim_inventory.json", result)
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({k: v for k, v in result.items() if k != "claims"}, indent=2))
