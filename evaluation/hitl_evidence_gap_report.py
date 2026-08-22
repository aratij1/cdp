"""Generate a truth-blind, field-level evidence-gap audit for every HITL record."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from packages.criticality import CriticalityPolicy, DEFAULT_CRITICALITY_PATH
from packages.domain.common import BoundingBox
from packages.evidence import EvidencePolicy, engine_family
from packages.evidence_decision import DecisionContext, EvidenceDecisionService
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.ocr.contracts import OCRCandidate


def _candidate(row: dict) -> OCRCandidate | None:
    value = row.get("value") or row.get("raw")
    if not value:
        return None
    engine = str(row.get("engine") or "unknown")
    return OCRCandidate(
        value=str(value), raw_value=str(row.get("raw") or value), engine=engine,
        model_name=engine, model_version=str(row.get("model_version") or "recorded"),
        preprocessing_variant=str(row.get("preprocessing") or "recorded"),
        raw_confidence=float(row.get("confidence") or 0), calibrated_confidence=None,
        bounding_box=BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1),
        latency_ms=0,
    )


def analyze(payload: dict) -> tuple[list[dict], dict]:
    criticality = CriticalityPolicy.load(DEFAULT_CRITICALITY_PATH)
    service = EvidenceDecisionService()
    policy: EvidencePolicy = service.evidence_policy
    deterministic_service = DeterministicEvidenceService()
    rows: list[dict] = []
    for document in payload["documents"]:
        document_id = str(document["document_id"])
        document_type = str(document.get("form_type") or document.get("document_type") or (
            "CMS1500" if document_id.startswith(("A-", "B-")) else
            "UB04" if document_id.startswith("C-") else
            "UNSTRUCTURED" if document_id.startswith("D-") else "UNKNOWN"
        ))
        claim_values = {
            item["field_name"]: item.get("normalized_value") or item.get("raw_value")
            for item in document["fields"]
        }
        charges = [
            item.get("normalized_value") or item.get("raw_value")
            for item in document["fields"]
            if item["field_name"] in {"charges", "total_charges", "charge_amount"}
            and (item.get("normalized_value") or item.get("raw_value"))
        ]
        if charges:
            claim_values["service_line_charges"] = ",".join(charges)
        for field in document["fields"]:
            if field.get("accepted", False):
                continue
            metadata = field.get("metadata") or {}
            candidates = [item for item in (_candidate(row) for row in metadata.get("ocr_candidates", [])) if item]
            candidates.sort(key=lambda item: item.raw_confidence, reverse=True)
            criticality_name = (
                "patient_name" if field["field_name"] in {"patient_first", "patient_last"}
                else field["field_name"]
            )
            level = criticality.for_field(criticality_name)
            if metadata.get("critical") and level.value == "C1":
                from packages.criticality import CriticalityLevel
                level = CriticalityLevel.C2
            deterministic = deterministic_service.evaluate(
                field["field_name"], field.get("normalized_value") or field.get("raw_value"),
                claim_values=claim_values,
            )
            hard_valid = deterministic.passed
            registration_raw = metadata.get("registration_confidence")
            registration = float(registration_raw) if registration_raw is not None else 1.0
            decision = service.decide(DecisionContext(
                field_name=field["field_name"], document_family=document_type,
                criticality=level, blocks_stp=level.value in {"C2", "C3"},
                candidates=candidates, deterministic_evidence=deterministic.evidence,
                hard_validation_passed=hard_valid, registration_confidence=registration,
                wrong_crop_suspected="WRONG_CROP_SUSPECTED" in metadata.get("reason_codes", []),
                cross_field_evidence=deterministic.cross_field_evidence,
            ))
            primary = candidates[0] if candidates else None
            secondary = next((item for item in candidates[1:]
                              if engine_family(item.engine) != engine_family(primary.engine)), None) if primary else None
            available = set(decision.available_evidence)
            e5_only = any(option <= available | {"E5"} for option in (
                {item.value for item in requirement}
                for requirement in policy.requirements(field["field_name"], level)
            )) and not any(option <= available for option in (
                {item.value for item in requirement}
                for requirement in policy.requirements(field["field_name"], level)
            ))
            rows.append({
                "document_id": document["document_id"], "document_type": document_type,
                "field_name": field["field_name"], "criticality": level.value,
                "blocking_status": level.value in {"C2", "C3"},
                "review_reason": ";".join(metadata.get("review_reason_codes") or metadata.get("reason_codes") or [str(field.get("validation_result") or "HITL")]),
                "candidate_value": field.get("raw_value"),
                "primary_engine": primary.engine if primary else None,
                "primary_confidence": primary.raw_confidence if primary else None,
                "secondary_engine": secondary.engine if secondary else None,
                "secondary_value": secondary.value if secondary else None,
                "secondary_confidence": secondary.raw_confidence if secondary else None,
                "registration_confidence": registration_raw,
                "deterministic_validation": {
                    "passed": hard_valid, "evidence": sorted(deterministic.evidence),
                    "failures": deterministic.failure_reasons,
                    "policy_version": deterministic_service.policy_version,
                },
                "reference_available": False, "reference_match": None,
                "cross_field_evidence": [],
                "AI_attempted": any(engine_family(item.engine) == "CLOUD_AI_FAMILY" for item in candidates),
                "available_evidence": decision.available_evidence,
                "missing_evidence": decision.missing_evidence,
                "cheapest_next_action": decision.next_action.value,
                "E5_would_satisfy_policy": e5_only,
                "final_reason_for_HITL": decision.reason_codes,
            })
    return rows, _summary(rows)


def _summary(rows: list[dict]) -> dict:
    reasons = Counter(reason for row in rows for reason in row["final_reason_for_HITL"])
    fields = Counter(row["field_name"] for row in rows)
    by_type: dict[str, Counter] = defaultdict(Counter)
    by_criticality: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_type[row["document_type"]].update(row["final_reason_for_HITL"])
        by_criticality[row["criticality"]].update(row["final_reason_for_HITL"])
    return {
        "review_fields": len(rows),
        "top_review_reasons": reasons.most_common(),
        "top_review_fields": fields.most_common(),
        "review_reasons_by_document_type": {key: value.most_common() for key, value in by_type.items()},
        "review_reasons_by_criticality": {key: value.most_common() for key, value in by_criticality.items()},
        "reviews_resolvable_if_E5_existed": sum(bool(row["E5_would_satisfy_policy"]) for row in rows),
    }


def _markdown(summary: dict) -> str:
    total = summary["review_fields"]
    lines = ["# CDP HITL Evidence Gap Report", "", f"Review fields analyzed: **{total}**", "",
             "## Evidence opportunity", "",
             f"Reviews whose current field policy would be satisfied by adding E5: **{summary['reviews_resolvable_if_E5_existed']}**",
             "", "## Top review reasons", "", "| Reason | Fields | Share |", "|---|---:|---:|"]
    lines.extend(f"| {reason} | {count} | {count / total:.2%} |" for reason, count in summary["top_review_reasons"][:20])
    lines.extend(["", "## Top review fields", "", "| Field | Reviews |", "|---|---:|"])
    lines.extend(f"| {field} | {count} |" for field, count in summary["top_review_fields"][:20])
    for heading, values in (("Review reasons by document type", summary["review_reasons_by_document_type"]),
                            ("Review reasons by criticality", summary["review_reasons_by_criticality"])):
        lines.extend(["", f"## {heading}", ""])
        for key, entries in sorted(values.items()):
            lines.extend([f"### {key}", "", "| Reason | Fields |", "|---|---:|"])
            lines.extend(f"| {reason} | {count} |" for reason, count in entries[:10])
            lines.append("")
    lines.extend(["## Method", "", "Truth-blind policy replay. Percentages use review fields as the denominator; reason codes are multi-label and can exceed 100% in total.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("docs/CDP_HITL_EVIDENCE_GAP_REPORT.md"))
    args = parser.parse_args()
    rows, summary = analyze(json.loads(args.predictions.read_text(encoding="utf-8")))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (args.output / "fields.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    with (args.output / "fields.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader(); writer.writerows(rows)
    args.report.write_text(_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
