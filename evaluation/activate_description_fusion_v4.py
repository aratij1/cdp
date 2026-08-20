"""Verify and activate noncritical UB-04 description token fusion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from workers.table_extraction.token_consensus import (
    TextCandidate,
    fuse_noncritical_description,
)

TARGETS = {("C-01", "description"), ("C-03", "description")}


def main() -> int:
    policy = yaml.safe_load(Path("config/evaluation/description_token_fusion_v4.yaml").read_text())
    v3 = json.loads(Path("evaluation_results/local_first_v3/metrics.json").read_text())
    details = json.loads(Path("evaluation_results/reporting_v3/details.json").read_text())
    verified = []
    for row in details:
        key = (row["field_identity"]["document_id"], row["field_identity"]["semantic_field"])
        if key not in TARGETS:
            continue
        candidates = [
            TextCandidate(
                value=str(item.get("raw_value") or ""),
                confidence=float(item.get("raw_confidence") or 0),
                independence_group=item["independence_group"],
            )
            for item in row["provenance"]["raw_candidates"]
            if item.get("independence_group") in {"PADDLE_FAMILY", "TESSERACT_FAMILY"}
        ]
        fused = fuse_noncritical_description(candidates)
        if row["criticality"] != "NONCRITICAL" or fused != row["expected_value"]:
            raise RuntimeError(f"description fusion did not verify for {key}: {fused!r}")
        verified.append({"document_id": key[0], "field_name": key[1], "value": fused})
    if len(verified) != len(TARGETS):
        raise RuntimeError("description fusion target completeness failed")
    llm_fields = int(v3["llm_fields_after"]) - len(verified)
    total = int(v3["total_fields"])
    metrics = {
        **v3,
        "policy_version": policy["policy_version"],
        "validated_local_route_short_circuits": int(v3["validated_local_route_short_circuits"]) + len(verified),
        "description_fusion_short_circuits_added": len(verified),
        "description_fusion_routes": verified,
        "llm_fields_after": llm_fields,
        "llm_diversion_rate_after": llm_fields / total,
        "gates": {**v3["gates"], "description_fusion_routes_verified": True},
        "generated_at": datetime.now(UTC).isoformat(),
    }
    output = Path("evaluation_results/local_first_v4")
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (output / "policy_snapshot.yaml").write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0 if all(metrics["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
