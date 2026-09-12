"""Owner-input adapters for the existing qualification controller; no extraction changes."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evaluation.candidate_runtime_freeze import (
    CANDIDATE as CANDIDATE,  # noqa: PLC0414 -- public compatibility export
)
from evaluation.claim_inventory import _publish, build_inventory
from packages.hitl_reduction.review_coordination import canonical_reviewer_id
from packages.real_data_evaluation.blind_workflow import FIELDS, content_digest
from packages.real_data_evaluation.qualification_jobs import publish


def read(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        raise ValueError("INVALID_QUALIFICATION_CONTRACT") from None
    if not isinstance(data, dict):
        raise ValueError("QUALIFICATION_CONTRACT_MAPPING_REQUIRED")
    return data


def registry_contract(path: Path, now: datetime | None = None) -> dict:
    """Only a complete, time-valid, independently assigned roster activates authority."""
    before = digest(path)
    data = load_contract(path)
    inactive = {"identity_verified": False, "authorized_reviewers": [], "adjudicators": []}
    if data.get("identity_verified") is not True or not data.get("policy_id"):
        return inactive
    now = now or datetime.now(UTC)
    people = []
    seen = set()
    for row in data.get("reviewers", []):
        if row.get("enabled") is not True:
            continue
        identity = canonical_reviewer_id(row.get("reviewer_id", ""))
        if not identity or identity in seen:
            raise ValueError("REGISTRY_DUPLICATE_OR_MISSING_IDENTITY")
        seen.add(identity)
        if (
            row.get("role") not in {"REVIEWER", "ADJUDICATOR"}
            or not row.get("independence_group")
            or not row.get("provenance")
            or not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(row.get("access_token_env", "")))
            or "TRACK_B_150" not in row.get("qualification_scope", [])
        ):
            raise ValueError("REGISTRY_GOVERNANCE_REQUIRED")
        start = datetime.fromisoformat(str(row["effective_from"]))
        end = datetime.fromisoformat(str(row["effective_to"]))
        if start.tzinfo is None or end.tzinfo is None or not start <= now < end:
            raise ValueError("REGISTRY_EFFECTIVE_WINDOW_REQUIRED")
        people.append({**row, "reviewer_id": identity})
    reviewers = [p for p in people if p["role"] == "REVIEWER"]
    adjudicators = [p for p in people if p["role"] == "ADJUDICATOR"]
    # Conservative policy: every enabled assignment must be mutually independent.
    if (
        len(reviewers) < 2
        or not adjudicators
        or len({p["independence_group"] for p in people}) != len(people)
    ):
        raise ValueError("INDEPENDENT_REVIEWERS_AND_ADJUDICATOR_REQUIRED")
    if digest(path) != before:
        raise ValueError("REVIEWER_CONTRACT_CHANGED_DURING_READ")
    return {
        "identity_verified": True,
        "policy_id": data["policy_id"],
        "authorized_reviewers": [p["reviewer_id"] for p in reviewers],
        "adjudicators": [p["reviewer_id"] for p in adjudicators],
        "assignments": people,
        "contract_sha256": before,
    }


def current_registry(root: Path, private: Path | None = None, *, synchronize: bool = False) -> dict:
    """The YAML is sole authority; a stale cache never authorizes a consumer."""
    private = private or root / "evaluation_results/qualification_closure"
    path = root / "config/qualification/reviewer_registry.yaml"
    disabled = {
        "identity_verified": False,
        "authorized_reviewers": [],
        "adjudicators": [],
        "assignments": [],
    }
    if not path.is_file():
        return {**disabled, "contract_status": "MISSING"}
    try:
        projected = registry_contract(path)
        if projected.get("identity_verified") is not True:
            return {**disabled, "contract_status": "INVALID"}
        cache_path = private / "reviewer_registry.local.json"
        cached = read(cache_path)
        if synchronize and (not cached or not cached.get("identity_verified")):
            _publish(cache_path, projected)
            cached = projected
        if cached != projected or digest(path) != cached.get("contract_sha256"):
            return {**disabled, "contract_status": "STALE"}
        return {**projected, "contract_status": "VALID"}
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        return {**disabled, "contract_status": "INVALID"}


def owner_approval(private: Path, csv_sha256: str, now: datetime | None = None) -> dict:
    path = private / "membership_owner_approval.local.json"
    if not path.is_file():
        return {"status": "PENDING"}
    try:
        receipt = read(path)
        stamp = datetime.fromisoformat(receipt["approved_at"])
        valid = (
            receipt.get("owner_id", "").strip().casefold() == "ashish singh"
            and receipt.get("owner_role") == "SOURCE_DATA_OWNER"
            and receipt.get("csv_sha256") == csv_sha256
            and isinstance(receipt.get("approval_reference"), str)
            and bool(receipt["approval_reference"].strip())
            and isinstance(receipt.get("policy_id"), str)
            and bool(receipt["policy_id"].strip())
            and stamp.tzinfo is not None
            and stamp <= (now or datetime.now(UTC))
        )
        return {
            "status": "PASS" if valid else "INVALID",
            "receipt_sha256": digest(path) if valid else None,
        }
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        return {"status": "INVALID"}


def ingest_membership(root: Path) -> dict:
    """Consume the single owner CSV; publish authority only after complete validation."""
    private = root / "evaluation_results/qualification_closure"
    target = root / "evaluation_results/real_release"
    path = target / "150_cohort_missing_membership.csv"
    seal_path = private / "membership_lineage_seal.local.json"
    if not path.exists() or not seal_path.exists():
        return {
            "status": "EXTERNAL_INPUT_REQUIRED",
            "reason": "OWNER_CSV_AND_LINEAGE_SEAL_REQUIRED",
        }
    approval = owner_approval(private, digest(path))
    prior = read(private / "claim_membership.local.json")
    if prior and prior.get("boundary_provenance", {}).get("approved_csv_sha256") != digest(path):
        raise ValueError("APPROVED_MEMBERSHIP_CHANGED")
    seal = read(seal_path)
    lookup_path = private / "blind_lineage_alias_lookup.local.json"
    if digest(lookup_path) != seal["lookup_sha256"]:
        raise ValueError("MEMBERSHIP_LOOKUP_CHANGED")
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if (
        len(rows) != len(seal["rows"])
        or len({r["review_page_alias"] for r in rows}) != len(rows)
        or {r["review_page_alias"] for r in rows} != set(seal["rows"])
    ):
        raise ValueError("MEMBERSHIP_PAGE_SCOPE_CHANGED")
    lookup = {p["review_page_alias"]: p for p in read(lookup_path)["pages"]}
    bindings = read(private / "source_page_bindings.local.json")["bindings"]
    actual = {b["source_page_id"]: b for b in bindings}
    grouped: dict[str, list] = defaultdict(list)
    states: Counter[str] = Counter()
    public = []
    for row in rows:
        alias = row["review_page_alias"]
        if {k: row[k] for k in seal["columns"]} != seal["rows"][alias]:
            raise ValueError("OWNER_SOURCE_LINEAGE_CHANGED")
        entry = lookup[alias]
        source = entry["source"]
        if actual.get(source["page_id"]) != entry["binding"]:
            raise ValueError("OWNER_BINDING_CHANGED")
        if row.get("membership_status") not in {"EXACT", "AMBIGUOUS", "UNBOUND"}:
            raise ValueError("INVALID_MEMBERSHIP_STATE")
        decision = row["owner_confirmation"].strip()
        claim = row["claim_alias_to_fill"].strip()
        state = "AMBIGUOUS" if decision == "AMBIGUOUS" else "UNBOUND"
        if claim and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", claim):
            raise ValueError("PHI_SAFE_CLAIM_ALIAS_REQUIRED")
        if decision in {"CONFIRM", "CORRECT"}:
            if (
                not claim
                or not row.get("document_alias")
                or not row.get("membership_provenance")
                or row.get("page_role") not in {"CLAIM_FORM", "ATTACHMENT"}
                or row.get("claim_complete_confirmed") != "YES"
                or row.get("membership_status") != "EXACT"
            ):
                raise ValueError("COMPLETE_OWNER_APPROVAL_REQUIRED")
            timestamp = datetime.fromisoformat(row["owner_approved_at"])
            if timestamp.tzinfo is None or timestamp > datetime.now(UTC):
                raise ValueError("OWNER_APPROVAL_TIMESTAMP_REQUIRED")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row["document_alias"]):
                raise ValueError("PHI_SAFE_DOCUMENT_ALIAS_REQUIRED")
            if int(row["claim_page_order"]) < 1:
                raise ValueError("CLAIM_PAGE_ORDER_REQUIRED")
            state = "EXACT" if approval["status"] == "PASS" else "UNBOUND"
        elif decision not in {"", "AMBIGUOUS"}:
            raise ValueError("INVALID_OWNER_DECISION")
        states[state] += 1
        if claim:
            grouped[claim].append((row, source, state))
        public.append({"review_page_alias": alias, "claim_alias": claim or None, "status": state})
    claims = {}
    excluded = 0
    for claim, members in grouped.items():
        if any(state != "EXACT" for _, _, state in members):
            excluded += 1
            continue
        members.sort(key=lambda item: int(item[0]["claim_page_order"]))
        if sorted(int(r["claim_page_order"]) for r, _, _ in members) != list(
            range(1, len(members) + 1)
        ):
            raise ValueError("CLAIM_PAGE_ORDER_CONFLICT")
        packages = {s["package_id"] for _, s, _ in members}
        if len(packages) != 1:
            raise ValueError("CLAIM_PACKAGE_CONFLICT")
        documents: dict = {}
        forms: list[str] = []
        attachments: list[str] = []
        for row, source, _ in members:
            doc = documents.setdefault(
                row["document_alias"],
                {
                    "page_ids": [],
                    "boundary": "CONFIRMED",
                    "boundary_provenance": content_digest(row),
                },
            )
            doc["page_ids"].append(source["page_id"])
            (forms if row["page_role"] == "CLAIM_FORM" else attachments).append(source["page_id"])
        claims[claim] = {
            "package_id": next(iter(packages)),
            "page_ids": [s["page_id"] for _, s, _ in members],
            "documents": documents,
            "claim_form_page_ids": forms,
            "attachment_page_ids": attachments,
            "expected_field_keys": [[p, f] for p in forms for f in FIELDS],
        }
    membership = {
        "governed": True,
        "complete_claim_membership_confirmed": True,
        "boundary_provenance": {
            "owner": "Ashish Singh",
            "role": "SOURCE_DATA_OWNER",
            "approved_csv_sha256": digest(path),
            "owner_approval_receipt_sha256": approval.get("receipt_sha256"),
        },
        "claims": claims,
    }
    inventory = build_inventory(membership, bindings)
    ready = (
        approval["status"] == "PASS"
        and states["EXACT"] == len(rows)
        and inventory["membership_ready"]
    )
    if ready:
        prior_membership = read(private / "claim_membership.local.json")
        if prior_membership and prior_membership != membership:
            raise ValueError("APPROVED_MEMBERSHIP_CHANGED")
        track_a_claims = {
            r["claim_id"]
            for r in read(private / "owner_sequence_membership.local.json").get("mappings", [])
        }
        if set(claims) & track_a_claims:
            raise ValueError("TRACK_A_CLAIM_OVERLAP")
        # Recheck actual source files and cross-track isolation before publishing authority.
        from evaluation.two_track_isolation import _build, assert_disjoint

        assert_disjoint(_build(root))
        for entry in lookup.values():
            s = entry["source"]
            if digest(Path(s["source_asset_path"])) != s["source_asset_sha256"]:
                raise ValueError("MEMBERSHIP_SOURCE_CHANGED")
        publish(private / "claim_membership.local.json", membership)
    report = {
        "status": "PASS" if ready else "EXTERNAL_INPUT_REQUIRED",
        "pages": len(rows),
        "exact_pages": states["EXACT"],
        "ambiguous_pages": states["AMBIGUOUS"],
        "unbound_pages": states["UNBOUND"],
        "claims_discovered": len(grouped),
        "exact_claims": inventory["claims_exactly_bound"],
        "excluded_claims": excluded + inventory["claims_ambiguous"] + inventory["claims_unbound"],
        "owner_approval": approval["status"],
        "membership_sha256": content_digest(membership) if ready else None,
        "issues": inventory["issues"],
        "truth_authority": False,
    }
    _publish(
        target / "track_b_claim_membership.json",
        {
            "status": report["status"],
            "pages": public,
            "membership_sha256": report["membership_sha256"],
            "scope": "ALIASED_MEMBERSHIP_ONLY",
        },
    )
    _publish(target / "track_b_claim_membership_report.json", report)
    return report


def prepare(root: Path) -> dict:
    from evaluation.candidate_runtime_freeze import readiness as candidate_readiness

    candidate = candidate_readiness(root)
    if candidate["status"] != "PASS":
        raise ValueError("QUALIFICATION_CANDIDATE_FREEZE_REQUIRED:" + candidate["status"])
    historical = read(root / "docs/qualification/track_b_completion/track_a_freeze.json")
    if historical and digest(root / "docs/closure/technical_closure/artifact_seal.json") != historical["track_a_artifact_seal_sha256"]:
        raise ValueError("TRACK_A_ARTIFACT_SEAL_CHANGED")
    membership = ingest_membership(root)
    private = root / "evaluation_results/qualification_closure"
    if (
        (private / "membership_lineage_seal.local.json").exists()
        and membership.get("status") != "PASS"
        and (private / "claim_membership.local.json").exists()
    ):
        raise ValueError("APPROVED_MEMBERSHIP_NO_LONGER_VALID")
    registry = current_registry(root, synchronize=True)
    _publish(private / "reviewer_authority_status.json", {"status": registry["contract_status"]})
    deployment: dict = {}
    deployment_path = root / "config/qualification/deployment_control.yaml"
    from evaluation.track_b_preflight import preflight

    if deployment_path.exists():
        try:
            config = load_contract(deployment_path)
        except (ValueError, OSError):
            config = {}
        result = preflight(config, directory=private)
        deployment = {}
        _publish(private / "deployment_preflight.json", result)
        if config.get("governed") is True and result["status"] == "PASS":
            _publish(private / "deployment_control.local.json", config)
            deployment = config
    else:
        _publish(private / "deployment_preflight.json", preflight({}, directory=private))
    return {"membership": membership, "registry": registry, "deployment": deployment}
