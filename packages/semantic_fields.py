"""Semantic source state is distinct from visible OCR and output projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SemanticFieldState(StrEnum):
    PRESENT = "PRESENT"
    BLANK = "BLANK"
    SOURCE_ABSENT = "SOURCE_ABSENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SAME_AS_PATIENT = "SAME_AS_PATIENT"
    SAME_AS_INSURED = "SAME_AS_INSURED"
    UNKNOWN = "UNKNOWN"
    UNREADABLE = "UNREADABLE"
    DERIVED_UNVERIFIED = "DERIVED_UNVERIFIED"


@dataclass(frozen=True)
class SemanticFieldValue:
    field_name: str
    semantic_state: SemanticFieldState
    source_value: str | None
    output_value: str | None
    rule_id: str | None
    rule_version: str | None
    evidence_references: tuple[str, ...]
    validated: bool

    @property
    def raw_ocr_value(self) -> str | None:
        return self.source_value

    @property
    def normalized_source_value(self) -> str | None:
        return self.source_value

    @property
    def projected_output_value(self) -> str | None:
        return self.output_value

    @property
    def projection_rule_id(self) -> str | None:
        return self.rule_id

    @property
    def projection_rule_version(self) -> str | None:
        return self.rule_version


@dataclass(frozen=True)
class SentinelProjectionRule:
    rule_id: str
    version: str
    field_name: str
    required_state: SemanticFieldState
    output_value: str
    authorization: str
    specification_reference: str | None = None


def project_output_sentinel(
    semantic: SemanticFieldValue, rule: SentinelProjectionRule
) -> SemanticFieldValue:
    if rule.authorization != "approved":
        raise ValueError(f"{rule.rule_id} is not an approved runtime business rule")
    if not rule.specification_reference:
        raise ValueError(f"{rule.rule_id} lacks a specification/business-rule reference")
    if semantic.field_name != rule.field_name:
        raise ValueError("sentinel rule applies to a different field")
    if semantic.semantic_state != rule.required_state or not semantic.validated:
        raise ValueError("semantic state has not satisfied the sentinel rule")
    return SemanticFieldValue(
        field_name=semantic.field_name,
        semantic_state=semantic.semantic_state,
        source_value=semantic.source_value,
        output_value=rule.output_value,
        rule_id=rule.rule_id,
        rule_version=rule.version,
        evidence_references=semantic.evidence_references,
        validated=True,
    )


def infer_same_as_state(
    *,
    field_name: str,
    source_value: str | None,
    counterpart_value: str | None,
    relationship_code: str | None,
    counterpart: SemanticFieldState,
    evidence_references: tuple[str, ...],
    claim_id: str | None = None,
    reference_fields: dict[str, SourceReference] | None = None,
    same_owner_approved_claim: bool = False,
) -> SemanticFieldValue:
    """Legacy adapter: implicit SELF/blank inference has no semantic authority."""
    if counterpart not in {
        SemanticFieldState.SAME_AS_PATIENT,
        SemanticFieldState.SAME_AS_INSURED,
    }:
        raise ValueError("counterpart must be a SAME_AS semantic state")
    resolution = (
        resolve_same_reference(field_name, claim_id, reference_fields,
                               owner_approved_complete=same_owner_approved_claim)
        if claim_id and reference_fields else None
    )
    validated = bool(resolution and resolution.validated
                     and resolution.source_value == source_value
                     and resolution.output_value == counterpart_value)
    if resolution:
        evidence_references = tuple(dict.fromkeys((*evidence_references, *resolution.evidence_references)))
    return SemanticFieldValue(
        field_name=field_name,
        semantic_state=counterpart if validated else SemanticFieldState.UNKNOWN,
        source_value=source_value,
        output_value=counterpart_value if validated else None,
        rule_id="EXPLICIT_SAME_CLAIM_REFERENCE" if validated else None,
        rule_version="1.0" if validated else None,
        evidence_references=evidence_references,
        validated=validated,
    )


@dataclass(frozen=True)
class SourceReference:
    claim_id: str
    value: str | None
    evidence: tuple[str, ...]
    refers_to: tuple[str, ...] = ()


def resolve_same_reference(
    field_name: str, claim_id: str, fields: dict[str, SourceReference], *,
    owner_approved_complete: bool,
) -> SemanticFieldValue:
    """Resolve an explicit, evidence-backed chain without discarding printed SAME."""
    seen: set[str] = set()
    evidence: list[str] = []
    current = field_name
    source = fields.get(field_name)
    value = None
    valid = owner_approved_complete and source is not None and source.value == "SAME"
    while valid:
        node = fields.get(current)
        if current in seen or node is None or node.claim_id != claim_id or not node.evidence:
            valid = False
            break
        seen.add(current)
        evidence.extend(node.evidence)
        if node.value != "SAME":
            valid = bool(node.value) and not node.refers_to
            value = node.value if valid else None
            break
        if len(node.refers_to) != 1:
            valid = False
            break
        current = node.refers_to[0]
    return SemanticFieldValue(
        field_name, SemanticFieldState.PRESENT if valid else SemanticFieldState.UNKNOWN,
        source.value if source else None, value if valid else None,
        "EXPLICIT_SAME_CLAIM_REFERENCE" if valid else None, "2.0" if valid else None,
        tuple(evidence), bool(valid),
    )


def membership_authority_blockers(membership: dict, claim_id: str) -> list[str]:
    """Validate the existing owner-ingested membership contract; never infer adjacency."""
    provenance = membership.get("boundary_provenance")
    if (membership.get("governed") is not True
            or membership.get("complete_claim_membership_confirmed") is not True
            or not isinstance(provenance, dict)
            or not provenance.get("owner_approval_receipt_sha256")
            or not provenance.get("approved_csv_sha256")):
        return ["OWNER_APPROVED_COMPLETE_MEMBERSHIP_REQUIRED"]
    claims = membership.get("claims", {})
    claim = claims.get(claim_id)
    if not isinstance(claim, dict):
        return ["CLAIM_MEMBERSHIP_MISSING"]
    pages = claim.get("page_ids", [])
    all_pages = [p for c in claims.values() for p in c.get("page_ids", [])]
    if not pages or len(all_pages) != len(set(all_pages)):
        return ["CLAIM_MEMBERSHIP_AMBIGUOUS"]
    documents = claim.get("documents", {})
    bound = [p for d in documents.values() for p in d.get("page_ids", [])]
    if (set(bound) != set(pages) or len(bound) != len(set(bound))
            or any(d.get("boundary") != "CONFIRMED" or not d.get("boundary_provenance")
                   for d in documents.values())):
        return ["DOCUMENT_OWNERSHIP_UNBOUND"]
    forms = claim.get("claim_form_page_ids", [])
    attachments = claim.get("attachment_page_ids", [])
    if (not forms or set(forms) & set(attachments)
            or len(forms + attachments) != len(set(forms + attachments))
            or set(forms + attachments) != set(pages)):
        return ["ATTACHMENT_OWNERSHIP_UNRESOLVED"]
    return []


def semantic_policy_digest() -> str:
    """Bind the comparator to canonical policy text across Windows/Linux checkout."""
    import hashlib
    from pathlib import Path

    policy = Path(__file__).resolve().parents[1] / "docs/qualification/DOCUMENT_SEMANTIC_AUTHORITY.md"
    return hashlib.sha256(policy.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
