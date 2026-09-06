"""Execute unconfigured authority paths and calculate conditional enablement."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from math import ceil
from pathlib import Path

from packages.claim_evidence.authoritative_snapshot import MatchStatus
from packages.claim_evidence.enablement import (
    IdentityAuthorityProvider,
    LookupResult,
    MemberAuthorityProvider,
    ProviderAuthorityProvider,
    SourceEvidenceProvider,
    SourceResult,
)
from packages.claim_evidence.lookup_runtime import BoundedAuthorityClient, independent_lookups
from packages.claim_evidence.source_review import ReviewStatus
from packages.claim_intelligence.enablement import (
    ClaimRequirements,
    evidence_scenario,
    minimum_enablement,
)
from packages.claim_intelligence.review_scenario import reviewed_scenario

ROOT = Path(__file__).resolve().parents[1]


def selective_review_path(
    claims: tuple[ClaimRequirements, ...], core: frozenset[str], target: float = 0.8
) -> dict:
    scenario = evidence_scenario(claims, core)
    if not 0 < target <= 1:
        raise ValueError("INVALID_TARGET")
    eligible = [
        c
        for c in claims
        if c.technical_blockers == 0 and c.requirements - core == {"SOURCE_REVIEW"}
    ]
    needed = max(0, ceil(target * len(claims)) - scenario["potentially_stp_capable_claims"])
    reachable = needed <= len(eligible)
    potential = scenario["potentially_stp_capable_claims"] + min(needed, len(eligible))
    return {
        "core_capabilities": sorted(core),
        "core_scenario": scenario,
        "eligible_source_review_claims": len(eligible),
        "additional_review_claims_required": needed if reachable else None,
        "target_reachable": reachable,
        "potentially_capable_claims_after_targeted_review": potential,
        "potential_stp": potential / len(claims),
        "potential_claim_hitl": 1 - potential / len(claims),
        "remaining_source_review_claims": len(eligible) - min(needed, len(eligible)),
        "achieved_production_stp": None,
        "production_qualified": False,
    }


async def deterministic_adapter_overhead() -> dict:
    """Synthetic event barriers establish overlap without simulating network latency."""
    entered = 0
    ready = asyncio.Event()

    async def transport(**query):
        nonlocal entered
        entered += 1
        if entered == 4:
            ready.set()
        await ready.wait()
        return LookupResult(
            MatchStatus.MATCH,
            "SYNTHETIC_DOUBLE",
            datetime.now(UTC),
            "TEST_ONLY",
            provenance_ids=("SYNTHETIC_RECORD:1",),
        )

    start = time.perf_counter()
    results = await independent_lookups(
        {
            name: (BoundedAuthorityClient(name, transport), {})
            for name in ("member", "provider", "identity", "source")
        }
    )
    return {
        "scope": "DETERMINISTIC_TEST_DOUBLES_NOT_PRODUCTION_NETWORK",
        "providers": 4,
        "all_entered_before_completion": entered == 4,
        "wall_ms": (time.perf_counter() - start) * 1000,
        "provider_elapsed_ms": {k: v.elapsed_ms for k, v in results.items()},
        "all_results_match": all(v.result.status == MatchStatus.MATCH for v in results.values()),
        "production_network_ms": None,
    }


def run() -> dict:
    path = ROOT / "evaluation_results/closure_iteration6/claim_evidence_matrix.json"
    rows = json.loads(path.read_text())
    claims = tuple(
        ClaimRequirements(r["claim_id_hash"], r["technical_blockers"], frozenset(r["capabilities"]))
        for r in rows
    )
    core = frozenset(
        {"MEMBER_AUTHORITY", "PROVIDER_AUTHORITY", "IDENTITY_AUTHORITY", "SOURCE_EVIDENCE"}
    )
    path_report = selective_review_path(claims, core)
    remaining = sorted(
        (
            c
            for c in claims
            if c.technical_blockers == 0 and c.requirements - core == {"SOURCE_REVIEW"}
        ),
        key=lambda c: c.claim_id,
    )
    required = path_report["additional_review_claims_required"]
    chosen = remaining[:required] if required is not None else []
    path_report["conditional_supplied_review_scenarios"] = {
        status.value: reviewed_scenario(claims, core, {c.claim_id: (status,) for c in chosen})
        for status in ReviewStatus
    }
    path_report["scenario_assumption"] = (
        "All required source-review fields of selected eligible claims have the supplied conclusion; no actual review was created."
    )
    path_report["claims_unlocked_per_capability"] = {}
    enabled: frozenset[str] = frozenset()
    previous = 0
    for capability in sorted(core):
        enabled = enabled | {capability}
        count = reviewed_scenario(claims, enabled, {})["potentially_stp_capable_claims"]
        path_report["claims_unlocked_per_capability"][capability] = {
            "cumulative_capabilities": sorted(enabled),
            "marginal_claims": count - previous,
            "cumulative_potential_claims": count,
        }
        previous = count
    path_report["authority"] = "CONDITIONAL_SCENARIO_NOT_ACHIEVED_STP"
    (ROOT / "docs/closure/minimum_stp_path.json").write_text(
        json.dumps(path_report, indent=2) + "\n"
    )
    results: dict[str, LookupResult | SourceResult] = {
        "member": MemberAuthorityProvider().lookup(
            member_id="", payer="", service_date=None, patient_name="", dob=""
        ),
        "provider": ProviderAuthorityProvider().lookup(
            npi="", provider_name="", role="", service_date=None
        ),
        **{
            role: IdentityAuthorityProvider().lookup(
                member_id="", payer="", service_date=None, person_role=role, name="", dob=""
            )
            for role in ("patient", "subscriber", "insured")
        },
        "source": SourceEvidenceProvider().lookup(package_id="", page_id="", attachment_id=""),
    }
    measured = asyncio.run(
        independent_lookups({k: (BoundedAuthorityClient(k), {}) for k in results})
    )
    report = {
        "authority": "ENGINEERING_SCENARIO_NOT_RELEASE_TRUTH",
        "claim_matrix_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "claims": len(claims),
        "minimum_enablement": minimum_enablement(claims),
        "selective_review_path": path_report,
        "deterministic_adapter_overhead": asyncio.run(deterministic_adapter_overhead()),
        "requirement_counts": dict(Counter(k for c in claims for k in c.requirements)),
        "adapters": {
            k: {
                "status": r.status.value,
                "reason": r.reason,
                "provenance_present": bool(r.provenance_ids),
                "unconfigured_dispatch_ms": measured[k].elapsed_ms,
                "external_lookup_latency_ms": None,
            }
            for k, r in results.items()
        },
        "configured_external_authorities": 0,
        "governed_source_review_records": 0,
        "policy_audit": {
            "status": "POLICY_REVIEW_REQUIRED",
            "rules_removed": 0,
            "reason": "Recorded cohort controls preserved; payer policy owners must establish applicability and redundancy. No authorization to bypass any control.",
        },
        "cost": {
            "paid_ai_calls": 0,
            "paid_ai_usd": 0,
            "external_lookup_usd": None,
            "ocr_compute_usd": None,
            "infrastructure_usd": None,
            "total_usd": None,
            "status": "PRICING_NOT_CONFIGURED",
        },
        "production_authority_activated": False,
        "release_truth_created": False,
        "production_metrics_status": "NOT_EVALUABLE_WITHOUT_TRUSTED_TRUTH",
    }
    out = ROOT / "docs/closure/production_evidence_readiness.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    run()
