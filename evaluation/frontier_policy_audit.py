"""Fail-closed audit of the frozen synthetic claim-STP frontier."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import yaml

from evaluation.production_readiness import FRONTIER, OUTPUT, verify_frontier


ACCEPTED = {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}
PROHIBITED_WITHOUT_AUTHORITY = {"E0", "E7", "E8"}


def _expected_policy_id(policies: dict, family: str, field: str, criticality: str) -> str:
    fields = policies.get("fields", {})
    if f"{family}.{field}" in fields:
        return f"{family}.{field}"
    if field in fields:
        return f"*.{field}"
    if criticality in policies.get("defaults", {}):
        return f"default.{criticality}"
    return "MISSING"


def _policy_options(policies: dict, family: str, field: str, criticality: str) -> list[list[str]]:
    fields = policies.get("fields", {})
    spec = (
        fields.get(f"{family}.{field}")
        or fields.get(field)
        or policies.get("defaults", {}).get(criticality)
        or {}
    )
    return spec.get("accept_any", [])


def audit_frontier(
    *, frontier: Path = FRONTIER,
    output: Path = OUTPUT / "policy_correctness_audit.json",
) -> dict:
    manifest = verify_frontier(frontier / "manifest.json")
    fields = json.loads((frontier / "field_dispositions.json").read_text("utf-8"))["rows"]
    claims = json.loads((frontier / "claim_dispositions.json").read_text("utf-8"))["claims"]
    policies = yaml.safe_load((frontier / "configs" / "evidence_policies.yaml").read_text("utf-8"))
    field_policy = yaml.safe_load(
        (frontier / "configs" / "field_acceptance_policies.yaml").read_text("utf-8")
    )
    routes = yaml.safe_load(
        (frontier / "configs" / "ocr_field_routes.yaml").read_text("utf-8")
    ).get("ocr_routes", {})

    by_claim: dict[str, list[dict]] = defaultdict(list)
    for row in fields:
        by_claim[row["document_id"]].append(row)

    violations: dict[str, list[dict]] = defaultdict(list)
    claim_results = []
    stp_claims = [claim for claim in claims if claim["stp_eligible"]]
    for claim in stp_claims:
        claim_id = claim["claim_id"]
        claim_fields = by_claim[claim_id]
        used_route_statuses: dict[str, str] = {}
        for row in claim_fields:
            family, field = row["document_family"], row["field_name"]
            configured = field_policy.get("forms", {}).get(family, {}).get(field)
            if not configured:
                violations["missing_field_policy_metadata"].append({
                    "claim_id": claim_id, "field": field, "family": family,
                })
                continue
            for key in ("criticality", "required", "blocks_stp", "requires_review_when_unresolved"):
                if row.get(key) != configured.get(key):
                    violations["field_policy_metadata_mismatch"].append({
                        "claim_id": claim_id, "field": field, "key": key,
                        "recorded": row.get(key), "configured": configured.get(key),
                    })
            if configured["required"] and configured["blocks_stp"] and row["final_disposition"] not in ACCEPTED:
                violations["unresolved_required_blocker"].append({
                    "claim_id": claim_id, "field": field,
                })

            expected_policy = _expected_policy_id(policies, family, field, row["criticality"])
            if row.get("current_evidence_policy") != expected_policy:
                violations["silent_policy_fallback"].append({
                    "claim_id": claim_id, "field": field,
                    "recorded": row.get("current_evidence_policy"),
                    "expected": expected_policy,
                })
            available = set(row.get("evidence_available", []))
            options = _policy_options(policies, family, field, row["criticality"])
            if row["criticality"] in {"C2", "C3"} and not any(
                set(option).issubset(available) for option in options
            ):
                violations["critical_evidence_policy_unsatisfied"].append({
                    "claim_id": claim_id, "field": field,
                    "available": sorted(available), "options": options,
                })
            if row["criticality"] in {"C2", "C3"}:
                prohibited = available & PROHIBITED_WITHOUT_AUTHORITY
                if "E5" in available and row.get("reference_evidence") != "AUTHORIZED":
                    prohibited.add("E5")
                if prohibited:
                    violations["prohibited_critical_evidence"].append({
                        "claim_id": claim_id, "field": field,
                        "evidence": sorted(prohibited),
                    })
            if "E3" not in available or (row.get("registration_evidence") or 0) < .80:
                violations["registration_or_structural_failure"].append({
                    "claim_id": claim_id, "field": field,
                })
            if row.get("evidence_bundle", {}).get("contradictions"):
                violations["suppressed_field_contradiction"].append({
                    "claim_id": claim_id, "field": field,
                })

            evidence_sources = {
                str(item.get("source", "")).casefold()
                for item in row.get("evidence_bundle", {}).get("evidence_items", [])
                if item.get("evidence_class") in {"E1", "E7"}
            }
            secondary_engines = {
                str(item.get("engine", "")).casefold()
                for item in row.get("secondary_candidates", [])
            }
            if not secondary_engines.issubset(evidence_sources):
                violations["untracked_secondary_candidate"].append({
                    "claim_id": claim_id, "field": field,
                    "untracked": sorted(secondary_engines - evidence_sources),
                })

            route = routes.get(field)
            if route and route.get("document_family", "*") in {"*", family}:
                confirmation = str(route.get("confirmation", "")).casefold()
                if confirmation in secondary_engines:
                    status = route.get("state", "DISABLED")
                    used_route_statuses[field] = status
                    if status == "EVALUATION_ONLY" and route.get("runtime_enabled"):
                        violations["evaluation_route_treated_as_production"].append({
                            "claim_id": claim_id, "field": field,
                        })

        if claim.get("contradictions"):
            violations["suppressed_claim_contradiction"].append({"claim_id": claim_id})
        production_eligible = not any(
            status in {"EXPERIMENTAL", "EVALUATION_ONLY", "SHADOW"}
            for status in used_route_statuses.values()
        )
        claim_results.append({
            "claim_id": claim_id,
            "evaluation_stp_qualified": True,
            "production_stp_eligible": production_eligible,
            "used_route_statuses": used_route_statuses,
        })

    # The frozen frontier must remain explicitly synthetic and non-authoritative.
    qualification_safe = manifest.get("qualification") == (
        "SYNTHETIC_EVALUATION_ONLY_NOT_PRODUCTION_AUTHORITY"
    )
    violation_counts = {name: len(rows) for name, rows in sorted(violations.items())}
    assertions = {
        "all_required_blocking_fields_resolved": not violations["unresolved_required_blocker"],
        "all_critical_fields_satisfy_policy": not violations["critical_evidence_policy_unsatisfied"],
        "no_blocking_contradiction": not (
            violations["suppressed_field_contradiction"]
            or violations["suppressed_claim_contradiction"]
        ),
        "registration_and_structural_checks_pass": not violations["registration_or_structural_failure"],
        "no_critical_field_relied_on_prohibited_evidence": not violations["prohibited_critical_evidence"],
        "no_evaluation_route_treated_as_production": not violations["evaluation_route_treated_as_production"],
        "no_misclassified_nonblocking_fields": not violations["field_policy_metadata_mismatch"],
        "no_missing_policy_metadata": not violations["missing_field_policy_metadata"],
        "no_silent_policy_fallback": not violations["silent_policy_fallback"],
        "no_untracked_secondary_candidate": not violations["untracked_secondary_candidate"],
        "synthetic_frontier_is_not_production_authority": qualification_safe,
    }
    report = {
        "audit_id": "EVIDENCE_FRONTIER_V2_POLICY_CORRECTNESS",
        "frontier": "EVIDENCE_FRONTIER_V2",
        "qualification": manifest.get("qualification"),
        "stp_claims_audited": len(stp_claims),
        "evaluation_stp_rate": len(stp_claims) / len(claims),
        "production_stp_eligible_claims": sum(
            row["production_stp_eligible"] for row in claim_results
        ),
        "production_authority_note": (
            "Evaluation-only evidence remains valid for the frozen evaluation metric, "
            "but confers no runtime or production promotion authority."
        ),
        "assertions": assertions,
        "all_assertions_pass": all(assertions.values()),
        "violation_counts": violation_counts,
        "violations": dict(violations),
        "claims": claim_results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = audit_frontier()
    print(json.dumps({
        key: report[key] for key in (
            "stp_claims_audited", "evaluation_stp_rate",
            "production_stp_eligible_claims", "all_assertions_pass",
        )
    }, indent=2))
    return 0 if report["all_assertions_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
