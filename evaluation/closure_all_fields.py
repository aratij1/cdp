"""Survey all frozen claim fields without changing the historical 130-field comparison."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from evaluation.cdp2_comparison import legacy_and_graph, write
from evaluation.closure_bottlenecks import decompose
from packages.candidate_reconciliation import EvidenceReconciler
from packages.claim_intelligence.normalization import normalize

ROOT = Path(__file__).resolve().parents[1]


def run() -> dict:
    raw = [
        json.loads(line)
        for line in (
            ROOT / "evaluation/baselines/phase8_12/inputs/source_b/policy_replay_input.jsonl"
        )
        .read_text()
        .splitlines()
        if line
    ]
    allowed = {
        "document_id",
        "family",
        "field_name",
        "final_value",
        "criticality",
        "candidates",
        "localization_evidence",
        "wrong_crop_suspected",
        "deterministic_validation",
    }
    groups = defaultdict(list)
    references = {}
    for row in raw:
        groups[row["document_id"]].append({k: v for k, v in row.items() if k in allowed})
        references[(row["document_id"], row["field_name"])] = row
    observations = []
    unknown_validation = 0
    for claim, inputs in groups.items():
        legacy, _, _ = legacy_and_graph(claim, inputs, EvidenceReconciler())
        for field in legacy.fields:
            row = references[(claim, field.field_name)]
            top = normalize(field.field_name, field.canonical_value or "")[0]
            candidates = [c.normalized_value or c.value for c in field.candidates]
            if top in candidates:
                candidates.remove(top)
                candidates.insert(0, top)
            unknown_validation += (
                normalize(field.field_name, field.canonical_value or "")[1] is None
            )
            observations.append(
                {
                    "claim_id": claim,
                    "field": field.field_name,
                    "form": legacy.form_type,
                    "criticality": row["criticality"],
                    "authority": "FROZEN_REGRESSION",
                    "truth": row["truth"],
                    "candidates": candidates,
                    "top1": top,
                    "accepted": field.accepted,
                    "authority_blocked": "AUTHORITATIVE_DATA_REQUIRED" in field.evidence_blockers,
                    "external_evidence_blocked": "EVIDENCE_REQUIRED" in field.evidence_blockers,
                }
            )
    result = decompose(observations, scope="ENGINEERING")
    result["normalization_not_evaluable_fields"] = unknown_validation
    result["normalization_unknown_is_not_pass"] = True
    result["historical_comparison_denominator_changed"] = False
    write(ROOT / "evaluation_results/closure", "all_field_candidate_diagnostic.json", result)
    return result


if __name__ == "__main__":
    result = run()
    print(result["summary"])
