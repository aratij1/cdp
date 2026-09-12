"""Resolve authority from scoped runtime evidence; confidence is not authority."""
from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import Field

from packages.claim_intelligence.normalization import comparison_key
from packages.domain.common import DomainModel
from packages.semantic_fields import membership_authority_blockers, semantic_policy_digest

if TYPE_CHECKING:
    from packages.evidence_decision.contracts import DecisionContext


class AuthorityState(StrEnum):
    VERIFIED = "AUTHORITY_VERIFIED"
    REFERENCE_REQUIRED = "AUTHORITY_REFERENCE_REQUIRED"
    MEMBERSHIP_REQUIRED = "AUTHORITY_MEMBERSHIP_REQUIRED"
    FORM_IDENTITY_REQUIRED = "AUTHORITY_FORM_IDENTITY_REQUIRED"
    AMBIGUOUS = "AUTHORITY_AMBIGUOUS"


class AuthorityResolution(DomainModel):
    state: AuthorityState = AuthorityState.FORM_IDENTITY_REQUIRED
    blockers: list[str] = Field(default_factory=lambda: ["AUTHORITY_FORM_IDENTITY_REQUIRED"])
    policy_sha256: str = "UNBOUND"
    resolver_version: str = "semantic-authority-v1"


def resolve_authority(context: DecisionContext, requirements: tuple[str, ...]) -> AuthorityResolution:
    try:
        return _resolve(context, requirements)
    except (TypeError, AttributeError, KeyError, ValueError):
        return AuthorityResolution(state=AuthorityState.AMBIGUOUS,
                                   blockers=[AuthorityState.AMBIGUOUS.value],
                                   policy_sha256=semantic_policy_digest())


def _resolve(context: DecisionContext, requirements: tuple[str, ...]) -> AuthorityResolution:
    blockers = []
    form = context.form_identity_authority
    if not (context.document_id and context.page_id and form.get("status") == "VERIFIED"
            and form.get("document_id") == context.document_id
            and form.get("document_family") == context.document_family
            and context.page_id in form.get("page_ids", [])
            and re.fullmatch(r"[a-f0-9]{64}", form.get("evidence_sha256", "")) and form.get("policy_version")):
        blockers.append(AuthorityState.FORM_IDENTITY_REQUIRED.value)
    membership = context.claim_membership_authority
    member_ok = bool(context.claim_id) and not membership_authority_blockers(membership, context.claim_id or "")
    claim = membership.get("claims", {}).get(context.claim_id, {})
    document = claim.get("documents", {}).get(context.document_id, {})
    if not (member_ok and context.page_id in document.get("page_ids", [])
            and context.page_id in claim.get("claim_form_page_ids", [])):
        blockers.append(AuthorityState.MEMBERSHIP_REQUIRED.value)
    reference = context.reference
    if "AUTHORITATIVE_REFERENCE" in requirements and not (
            context.reference_source_state.value == "AUTHORIZED" and reference
            and reference.verified and not reference.contradiction and not reference.conflicts
            and reference.source and reference.version and reference.reference_key
            and re.fullmatch(r"[a-f0-9]{64}", reference.snapshot_checksum or "") and reference.matched_attributes
            and reference.value and context.candidates
            and all(comparison_key(context.field_name, candidate.value or "") == comparison_key(context.field_name, reference.value or "")
                    for candidate in context.candidates)):
        blockers.append(AuthorityState.REFERENCE_REQUIRED.value)
    if (context.semantic_blockers or context.source_role != "CLAIM_FORM"
            or context.semantic_state not in {"VALUE", "PRESENT"}
            or (reference and (reference.contradiction or reference.conflicts))
            or any((candidate.raw_value or "").strip().upper() == "SAME" for candidate in context.candidates)):
        blockers.append(AuthorityState.AMBIGUOUS.value)
    state = AuthorityState.AMBIGUOUS if AuthorityState.AMBIGUOUS.value in blockers else AuthorityState(blockers[0]) if blockers else AuthorityState.VERIFIED
    return AuthorityResolution(state=state, blockers=blockers, policy_sha256=semantic_policy_digest())
