"""Coverage of actual runtime emitters; completeness does not approve automation."""
from __future__ import annotations

from pathlib import Path

import yaml

from packages.deterministic_evidence import DeterministicEvidenceService
from packages.evidence import EvidencePolicy
from packages.field_policy import FieldPolicyRegistry
from packages.layout_intelligence.schema import SCHEMAS

ROOT = Path(__file__).resolve().parents[1]
VALIDATION_RULE = "DETERMINISTIC_FIELD_AND_CLAIM_INVARIANTS"


def supported_runtime_fields(root: Path = ROOT) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    def names(node):
        if isinstance(node, dict):
            if "field_name" in node:
                yield node["field_name"]
            for value in node.values():
                yield from names(value)
        elif isinstance(node, list):
            for value in node:
                yield from names(value)
    for path in (root / "config/templates").glob("*.yaml"):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        result.setdefault(spec["form_type"], set()).update(names(spec))
    labels = yaml.safe_load((root / "config/layout_label_aliases.yaml").read_text(encoding="utf-8"))
    families = yaml.safe_load((root / "config/unstructured_document_families.yaml").read_text(encoding="utf-8"))
    generic = set(labels["fields"]) | {name for family in families["families"].values()
                                         for name in family.get("fields", {})}
    for family in {*SCHEMAS, "UNKNOWN", "NON_CLAIM", "UNSTRUCTURED"}:
        result.setdefault(family, set()).update(generic)
    routes = yaml.safe_load((root / "config/ocr_field_routes.yaml").read_text(encoding="utf-8"))
    for route in routes["ocr_routes"].values():
        if route.get("status") == "PRODUCTION_APPROVED":
            result.setdefault(route["form"], set()).add(route["field"])
    return result


def policy_coverage(registry: FieldPolicyRegistry, evidence: EvidencePolicy,
                    supported: dict[str, set[str]] | None = None) -> dict:
    rows = []
    for family, names in sorted((supported if supported is not None else supported_runtime_fields()).items()):
        for name in sorted(names):
            policy = registry.for_field(family, name)
            failures = []
            contract = registry.explicit_contract(family, name)
            if contract.get("criticality") not in {"C0", "C1", "C2", "C3"}:
                failures.append("EXPLICIT_CRITICALITY_REQUIRED")
            if any(type(contract.get(flag)) is not bool for flag in
                   ("required", "blocks_stp", "requires_review_when_unresolved")):
                failures.append("EXPLICIT_OBLIGATION_REQUIRED")
            if not registry.is_explicitly_configured(family, name):
                failures.append("ACCEPTANCE_POLICY_MISSING")
            if policy.validation_rule != VALIDATION_RULE or policy.validation_version != DeterministicEvidenceService.policy_version:
                failures.append("VALIDATION_POLICY_MISSING_OR_STALE")
            if contract.get("disposition_mode") not in {"EVIDENCE_GATED", "REVIEW_REQUIRED"}:
                failures.append("EXPLICIT_DISPOSITION_REQUIRED")
            if not policy.evidence_requirements:
                failures.append("EVIDENCE_REQUIREMENTS_MISSING")
            if policy.disposition_mode == "EVIDENCE_GATED" and not evidence.requirements(policy.canonical_field_name, policy.criticality, family):
                failures.append("AUTOMATIC_EVIDENCE_POLICY_MISSING")
            if policy.disposition_mode == "REVIEW_REQUIRED" and (not policy.blocks_stp or not policy.requires_review_when_unresolved):
                failures.append("REVIEW_POLICY_MUST_BLOCK_STP")
            rows.append({"family":family, "field":name, "canonical_field":policy.canonical_field_name,
                         "criticality":policy.criticality.value, "required":policy.required,
                         "blocks_stp":policy.blocks_stp, "validation_rule":policy.validation_rule,
                         "validation_version":policy.validation_version,
                         "evidence_requirements":list(policy.evidence_requirements),
                         "disposition_mode":policy.disposition_mode, "failures":failures})
    uncovered_count = sum(bool(row["failures"]) for row in rows)
    return {"status":"CONFIGURATION_INCOMPLETE" if uncovered_count or not rows else "READY",
            "fields":rows, "supported_field_family_pairs":len(rows), "uncovered":uncovered_count,
            "automation_approval_implied":False}
