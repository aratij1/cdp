"""Activate validated geometry/crop short-circuits over local-first v1."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

TARGETS = {
    ("A-11", "rel_code"),
    ("D-03", "rel_code"),
    ("C-03", "patient_sex"),
    ("C-05", "patient_sex"),
}


def main() -> int:
    policy = yaml.safe_load(Path("config/evaluation/crop_local_first_v2.yaml").read_text())
    v1 = json.loads(Path("evaluation_results/local_first_v1/metrics.json").read_text())
    details = json.loads(
        Path("evaluation_results/targeted_diagnostics_v1/evaluation/details.json").read_text()
    )
    verified = {
        (row["document_id"], row["field_name"])
        for row in details
        if row.get("correct_candidate_generated")
        and (row["document_id"], row["field_name"]) in TARGETS
    }
    if verified != TARGETS:
        missing = sorted(TARGETS - verified)
        raise RuntimeError(f"geometry promotion evidence incomplete: {missing}")

    local_short_circuits = int(v1["validated_local_route_short_circuits"]) + len(verified)
    llm_fields = int(v1["unique_llm_eligible_fields_before"]) - int(
        v1["reference_short_circuits"]
    ) - local_short_circuits - int(v1["semantic_short_circuits"])
    total = int(v1["total_fields"])
    metrics = {
        **v1,
        "policy_version": policy["policy_version"],
        "validated_local_route_short_circuits": local_short_circuits,
        "geometry_crop_short_circuits_added": len(verified),
        "geometry_routes": [
            {"document_id": document_id, "field_name": field_name}
            for document_id, field_name in sorted(verified)
        ],
        "llm_fields_after": llm_fields,
        "llm_diversion_rate_after": llm_fields / total,
        "gates": {
            "accuracy_remains_100_percent": v1["accuracy_after"] == 1.0,
            "llm_diversion_below_8_percent": llm_fields / total < 0.08,
            "no_previous_regressions": v1["previously_correct_field_regressions"] == 0,
            "critical_false_accepts_zero": v1["critical_false_accepts"] == 0,
            "all_geometry_routes_verified": verified == TARGETS,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    output = Path("evaluation_results/local_first_v2")
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output / "policy_snapshot.yaml").write_text(
        yaml.safe_dump(policy, sort_keys=False), encoding="utf-8"
    )
    print(json.dumps(metrics, indent=2))
    return 0 if all(metrics["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
