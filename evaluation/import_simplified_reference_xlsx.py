"""Import the reviewer-friendly reference workbook with fail-closed validation."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from evaluation.import_governed_reference_xlsx import read_sheet

TRUE_VALUES = {"1", "true", "yes", "y"}


def _iso_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "T" in value
    except ValueError:
        return False


def validate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    accepted: list[dict[str, str]] = []
    audit: list[dict[str, object]] = []
    required = (
        "identity_key", "reference_value", "authorized_source_system",
        "source_dataset_version", "source_record_id", "matching_attributes",
        "primary_reviewer", "primary_approved_at", "second_reviewer",
        "second_approved_at",
    )
    for row in rows:
        reasons = [f"MISSING_{name.upper()}" for name in required if not row.get(name)]
        decision = row.get("decision", "").upper()
        if decision != "REFERENCE_VERIFIED":
            reasons.append("DECISION_NOT_REFERENCE_VERIFIED")
        try:
            attributes = json.loads(row.get("matching_attributes", "[]"))
            if not isinstance(attributes, list) or len(set(attributes)) < 2:
                reasons.append("INSUFFICIENT_MATCHING_ATTRIBUTES")
        except json.JSONDecodeError:
            reasons.append("INVALID_MATCHING_ATTRIBUTES")
        if row.get("contradictions", "").strip() not in {"", "[]"}:
            reasons.append("CONTRADICTION_PRESENT")
        if row.get("claim_revalidated", "").lower() not in TRUE_VALUES:
            reasons.append("CLAIM_NOT_REVALIDATED")
        if row.get("primary_reviewer", "").lower() == row.get("second_reviewer", "").lower():
            reasons.append("SECOND_REVIEWER_NOT_INDEPENDENT")
        for name in ("primary_approved_at", "second_approved_at"):
            if row.get(name) and not _iso_timestamp(row[name]):
                reasons.append(f"INVALID_{name.upper()}")
        parts = row.get("identity_key", "").split("|")
        if len(parts) != 4:
            reasons.append("INVALID_IDENTITY_KEY")
            canonical_key = row.get("identity_key", "")
        else:
            canonical_key = "|".join((parts[0], parts[1], parts[2], "", parts[3]))
        status = "ACCEPTED" if not reasons else "NOT_APPLIED"
        audit.append({
            "source_identity_key": row.get("identity_key", ""),
            "canonical_identity_key": canonical_key,
            "decision": decision,
            "status": status,
            "reasons": reasons,
            "source_record_id": row.get("source_record_id", ""),
        })
        if status == "ACCEPTED":
            accepted.append({"identity_key": canonical_key, "decision": decision})
    return accepted, audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [row for row in read_sheet(args.workbook, "FILL THESE ROWS") if row.get("identity_key")]
    accepted, audit = validate(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {
        "workbook_rows": len(rows),
        "accepted_decisions": len(accepted),
        "pending_or_rejected": len(rows) - len(accepted),
    }
    (args.output / "reference_decisions.json").write_text(json.dumps(accepted, indent=2), encoding="utf-8")
    (args.output / "import_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
