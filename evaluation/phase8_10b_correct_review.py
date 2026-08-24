"""Canonical Phase 8.10B correct-but-reviewed and claim-unlock analysis."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from packages.claim_decision import ClaimDecisionContext
from packages.evidence import StructuralLocalizationEvidence
from packages.evidence.name_agreement import compare_patient_names
from packages.evidence_decision import DecisionContext, FieldDecision, FieldDisposition
from packages.runtime_profile import DecisionServiceFactory

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "evaluation_results/phase8_10"
OUTPUT = ROOT / "evaluation_results/phase8_10b"
DOCS = ROOT / "docs"
SOURCES = ("source_a", "source_b", "source_c")
ACCEPTED = {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")


def _correct(row: dict, selected: str | None) -> bool:
    if (selected or "").strip().casefold() == (row["truth"] or "").strip().casefold():
        return True
    return row["field_name"] in {"patient_name", "insured_name", "provider_name"} and (
        compare_patient_names(selected, row["truth"]).agrees
    )


def _missing_categories(decision: FieldDecision) -> list[str]:
    missing = set(decision.missing_evidence)
    categories = [f"MISSING_{item}" for item in sorted(missing) if item in {"E2", "E3", "E4", "E5", "E6"}]
    reasons = set(decision.reason_codes)
    if any("CORRELATED" in reason for reason in reasons):
        categories.append("CORRELATED_EVIDENCE_ONLY")
    if any(reason.startswith("ROUTE_STATUS_REJECTED") for reason in reasons):
        categories.append("ROUTE_NOT_PRODUCTION_ELIGIBLE")
    if decision.runtime_profile_id == "UNBOUND":
        categories.append("POLICY_CONFIG_MISMATCH")
    if any("REFERENCE_NOT_AUTHORIZED" in reason for reason in reasons):
        categories.append("REFERENCE_NOT_AUTHORIZED")
    return categories or ["OTHER"]


def run() -> dict:
    bundle = DecisionServiceFactory.from_profile()
    rows: list[dict] = []
    decisions_by_claim: dict[str, list[FieldDecision]] = defaultdict(list)
    family_by_claim: dict[str, str] = {}
    correct_reviewed_by_claim: dict[str, set[str]] = defaultdict(set)
    all_decision_rows: list[tuple[dict, FieldDecision, bool]] = []

    for source in SOURCES:
        for row in _read_jsonl(INPUT / source / "policy_replay_input.jsonl"):
            policy = bundle.field_policy.for_field(row["family"], row["field_name"])
            decision = bundle.evidence_decision.decide(
                DecisionContext(
                    field_id=f"{row['document_id']}:{row['field_name']}",
                    field_name=row["field_name"],
                    document_family=row["family"],
                    criticality=policy.criticality,
                    required=policy.required,
                    blocks_stp=policy.blocks_stp,
                    requires_review_when_unresolved=policy.requires_review_when_unresolved,
                    candidates=row["candidates"],
                    deterministic_evidence=set(row["deterministic_validation"]["evidence"]),
                    deterministic_evidence_version=row["deterministic_validation"]["version"],
                    hard_validation_passed=row["deterministic_validation"]["passed"],
                    structural_localization=StructuralLocalizationEvidence.model_validate(
                        row["localization_evidence"]
                    ),
                    wrong_crop_suspected=row["wrong_crop_suspected"],
                    cross_field_evidence=set(row["cross_field_evidence"]),
                )
            )
            claim_id = row["document_id"]
            decisions_by_claim[claim_id].append(decision)
            family_by_claim[claim_id] = row["family"]
            is_correct_reviewed = decision.disposition not in ACCEPTED and _correct(
                row, decision.selected_value
            )
            all_decision_rows.append((row, decision, _correct(row, decision.selected_value)))
            if is_correct_reviewed:
                correct_reviewed_by_claim[claim_id].add(row["field_name"])
                rows.append(
                    {
                        "document_id": claim_id,
                        "source": source.upper(),
                        "form": row["family"],
                        "field": row["field_name"],
                        "truth": row["truth"],
                        "selected_value": decision.selected_value,
                        "disposition": decision.disposition.value,
                        "next_action": decision.next_action.value,
                        "missing_evidence": sorted(decision.missing_evidence),
                        "categories": _missing_categories(decision),
                        "reason_codes": decision.reason_codes,
                        "runtime_profile_id": decision.runtime_profile_id,
                        "policy_version": decision.policy_version,
                        "route_mode": decision.route_mode,
                    }
                )

    claims = {}
    for claim_id, field_decisions in sorted(decisions_by_claim.items()):
        claim = bundle.claim_decision.decide(
            ClaimDecisionContext(
                claim_id=claim_id,
                document_family=family_by_claim[claim_id],
                field_decisions=field_decisions,
                policy_id=bundle.claim_decision.policy_id,
                policy_version=bundle.claim_decision.policy_version,
            )
        )
        claims[claim_id] = claim

    category_counts = Counter(category for row in rows for category in row["categories"])
    field_counts = Counter((row["form"], row["field"]) for row in rows)
    missing_by_field: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        missing_by_field[(row["form"], row["field"])].update(row["categories"])

    unlock = []
    for (form, field), count in field_counts.items():
        blocked = 0
        singles = 0
        for claim_id, claim in claims.items():
            if family_by_claim[claim_id] != form or field not in correct_reviewed_by_claim[claim_id]:
                continue
            blockers = set(claim.blocking_unresolved_fields)
            if field in blockers:
                blocked += 1
                singles += len(blockers) == 1
        dominant = missing_by_field[(form, field)].most_common(1)[0][0]
        cheapest = {
            "MISSING_E2": "independent local representation",
            "MISSING_E3": "qualified structural localization",
            "MISSING_E4": "deterministic claim/format check",
            "MISSING_E5": "authorized reference lookup",
            "MISSING_E6": "cross-field claim reconciliation",
            "CORRELATED_EVIDENCE_ONLY": "independent local representation",
            "ROUTE_NOT_PRODUCTION_ELIGIBLE": "production route qualification",
        }.get(dominant, "targeted evidence audit")
        unlock.append(
            {
                "form": form,
                "field": field,
                "correct_reviewed_count": count,
                "claims_blocked": blocked,
                "single_blocker_claims": singles,
                "dominant_missing_evidence": dominant,
                "lowest_cost_legitimate_evidence": cheapest,
                "claims_potentially_unlocked": singles,
            }
        )
    unlock.sort(key=lambda item: (-item["single_blocker_claims"], -item["correct_reviewed_count"], item["form"], item["field"]))

    accepted_rows = [item for item in all_decision_rows if item[1].disposition in ACCEPTED]
    false_accepts = [
        {
            "document_id": row["document_id"],
            "form": row["family"],
            "field": row["field_name"],
            "truth": row["truth"],
            "selected_value": decision.selected_value,
            "criticality": row["criticality"],
            "reason_codes": decision.reason_codes,
        }
        for row, decision, correct in accepted_rows
        if not correct
    ]
    summary = {
        "runtime_profile_id": bundle.profile.decision_identity()["runtime_profile_id"],
        "total_correct_but_reviewed": len(rows),
        "category_counts": dict(category_counts),
        "claims": len(claims),
        "claim_stp": sum(claim.stp_eligible for claim in claims.values()) / max(1, len(claims)),
        "field_hitl": 1 - len(accepted_rows) / max(1, len(all_decision_rows)),
        "accepted_precision": sum(item[2] for item in accepted_rows) / max(1, len(accepted_rows)),
        "critical_false_accepts": sum(
            not correct and decision.disposition in ACCEPTED and row["criticality"] == "C1"
            for row, decision, correct in all_decision_rows
        ),
        "false_accept_records": false_accepts,
        "claim_unlock_opportunities": unlock,
    }
    _write_jsonl(OUTPUT / "correct_reviewed_records.jsonl", rows)
    (OUTPUT / "correct_reviewed_summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")

    category_lines = "\n".join(f"| {key} | {value} |" for key, value in category_counts.most_common())
    (DOCS / "CDP_PHASE8_10B_CORRECT_REVIEW_EVIDENCE_PARETO.md").write_text(
        "# Phase 8.10B Correct-but-reviewed evidence Pareto\n\n"
        f"Canonical profile: `{bundle.profile.decision_identity()['runtime_profile_id']}`. Correct-but-reviewed fields: **{len(rows)}**. "
        "Counts are evidence-gap tags and may overlap when a field lacks more than one class. No OCR was rerun for this analysis.\n\n"
        "| Evidence gap | Count |\n|---|---:|\n" + category_lines + "\n",
        "utf-8",
    )
    top_lines = "\n".join(
        f"| {item['form']} | {item['field']} | {item['correct_reviewed_count']} | {item['claims_blocked']} | {item['single_blocker_claims']} | {item['dominant_missing_evidence']} | {item['lowest_cost_legitimate_evidence']} |"
        for item in unlock[:20]
    )
    (DOCS / "CDP_PHASE8_10B_NEXT_BOTTLENECK.md").write_text(
        "# Phase 8.10B next bottleneck\n\n"
        "| Form | Field | Correct reviewed | Claims blocked | Single blockers | Missing evidence | Lowest-cost legitimate evidence |\n"
        "|---|---|---:|---:|---:|---|---|\n" + top_lines + "\n\n"
        "The next experiment is selected from single-blocker claim value; this report does not implement it.\n",
        "utf-8",
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
