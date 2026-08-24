"""Canonical Phase 8.2 safety, HITL, STP, secondary-value, and cost analysis."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from packages.claim_decision import ClaimDecisionContext, ClaimDecisionService
from packages.criticality import CriticalityLevel
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.domain.common import BoundingBox
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDisposition
from packages.ocr.contracts import OCRCandidate
from packages.ocr.provenance import EvidenceProvenance

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "evaluation_results/phase8_2/golden_uncached"
DEFAULT_OUTPUT = ROOT / "evaluation_results/phase8_2"
ACCEPTED = {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED}
SAFE_REJECTED = {
    FieldDisposition.ESCALATE, FieldDisposition.HUMAN_REVIEW_REQUIRED,
    FieldDisposition.INSUFFICIENT_EVIDENCE, FieldDisposition.UNRESOLVED_NON_BLOCKING,
    FieldDisposition.REJECTED,
}


def _canonical(value) -> str:
    return " ".join(str(value or "").upper().split())


def _candidate(value: str, confidence: float, bbox: list[int], *, engine: str,
               variant: str, reference: str) -> OCRCandidate:
    x0, y0, x1, y1 = bbox
    return OCRCandidate(
        value=value, raw_value=value, engine=engine, model_name="RapidOCR-ONNX",
        model_version="rapidocr-onnxruntime", preprocessing_variant=variant,
        raw_confidence=max(0, min(1, confidence)), calibrated_confidence=None,
        bounding_box=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1,
                                 image_width=max(1, x1), image_height=max(1, y1)),
        latency_ms=0, evidence_reference=reference,
    )


def _candidates(row: dict) -> list[OCRCandidate]:
    persisted = row.get("ocr_candidates") or []
    if persisted:
        values = []
        for item in persisted:
            provenance = EvidenceProvenance.model_validate(item["provenance"]) if (
                item.get("provenance")
            ) else None
            bbox = BoundingBox.model_validate(
                item.get("bounding_box") or {
                    "x0": row["predicted_bbox"][0], "y0": row["predicted_bbox"][1],
                    "x1": row["predicted_bbox"][2], "y1": row["predicted_bbox"][3],
                    "image_width": max(1, row["predicted_bbox"][2]),
                    "image_height": max(1, row["predicted_bbox"][3]),
                }
            )
            values.append(OCRCandidate(
                value=item.get("raw_text"), raw_value=item.get("raw_text") or "",
                engine=(provenance.engine_name if provenance and provenance.engine_name
                        else str(item.get("source", "unknown"))),
                model_name=item.get("model_name") or "unknown",
                model_version=item.get("model_version") or "unknown",
                preprocessing_variant=(
                    provenance.preprocessing_profile
                    if provenance and provenance.preprocessing_profile else "unknown"
                ),
                raw_confidence=float(item.get("confidence") or 0),
                calibrated_confidence=None, bounding_box=bbox, latency_ms=0,
                evidence_reference=str(item.get("evidence_id") or ""),
                preprocessing_version=(
                    provenance.preprocessing_version
                    if provenance and provenance.preprocessing_version else "unknown"
                ),
                provenance=provenance,
            ))
        return values
    trace = row.get("candidate_trace") or {}
    values = []
    primary = trace.get("primary_value")
    if primary:
        values.append(_candidate(
            primary, row.get("ocr_confidence") or 0, row["predicted_bbox"],
            engine="rapidocr_full_page", variant="page-observation",
            reference=f"{row['document_id']}:{row['field_name']}:primary",
        ))
    regional = trace.get("regional_value")
    if regional:
        values.append(_candidate(
            regional, trace.get("regional_confidence") or 0, row["predicted_bbox"],
            engine="rapidocr_regional", variant="high-resolution-region",
            reference=f"{row['document_id']}:{row['field_name']}:regional",
        ))
    if not values and row.get("final"):
        values.append(_candidate(
            row["final"], row.get("ocr_confidence") or 0, row["predicted_bbox"],
            engine="rapidocr", variant="persisted-field",
            reference=f"{row['document_id']}:{row['field_name']}:persisted",
        ))
    return values


def _root_cause(row: dict) -> str:
    if row["failure_layer"] == "FIELD_LOCALIZATION":
        return "LOCALIZATION_FALSE_POSITIVE"
    if row["field_name"] in {"patient_name", "provider_name", "insured_name"}:
        return "NAME_ACCEPTANCE_TOO_WEAK"
    if "member" in row["field_name"] or "npi" in row["field_name"]:
        return "ID_ACCEPTANCE_TOO_WEAK"
    if "date" in row["field_name"]:
        return "DATATYPE_VALIDATION_TOO_WEAK"
    if row["failure_layer"] == "NORMALIZATION_OR_PARSER":
        return "NORMALIZATION_FALSE_POSITIVE"
    return "OCR_FALSE_POSITIVE"


def _review_category(reason_codes: list[str]) -> str:
    joined = " ".join(reason_codes)
    if any(value in joined for value in ("CROP", "REGISTRATION", "STRUCTUR")):
        return "STRUCTURAL"
    if "CONTRADICTION" in joined:
        return "CONTRADICTION"
    if any(value in joined for value in ("MISSING", "INSUFFICIENT", "ACQUIRE")):
        return "EVIDENCE_GAP"
    if any(value in joined for value in ("AMBIGU", "CALIBRATION")):
        return "TRUE_AMBIGUITY"
    if any(value in joined for value in ("INVALID", "VALIDATION", "FORMAT")):
        return "EXTRACTION_UNCERTAINTY"
    return "UNSUPPORTED"


def analyze(input_run: Path = DEFAULT_RUN, output: Path = DEFAULT_OUTPUT) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (input_run/"field_records.jsonl").read_text("utf-8").splitlines()]
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_doc[row["document_id"]].append(row)

    evidence = EvidenceDecisionService(route_mode="runtime")
    deterministic = DeterministicEvidenceService()
    field_decisions = []
    false_accepts = []
    wrong = safe_rejections = correct_accepted = accepted_count = critical_accepted = 0
    correct_critical_accepted = critical_total = 0
    review_reasons = Counter()
    doc_decisions = defaultdict(list)
    for row in rows:
        policy = evidence.field_policy.for_field(row["family"], row["field_name"])
        value = row.get("final")
        facts = deterministic.evaluate(row["field_name"], value)
        confidence = row.get("structural_confidence")
        decision = evidence.decide(DecisionContext(
            field_id=f"{row['document_id']}:{row['field_name']}",
            field_name=row["field_name"], document_family=row["family"],
            criticality=policy.criticality, required=policy.required,
            blocks_stp=policy.blocks_stp,
            requires_review_when_unresolved=policy.requires_review_when_unresolved,
            candidates=_candidates(row), deterministic_evidence=facts.evidence,
            # Preserve the extraction candidate's hard-invalid state. The
            # canonical policy may add evidence, but it must never turn a
            # candidate already rejected by datatype/contamination checks
            # back into an accepted value.
            hard_validation_passed=(facts.passed and bool(row.get("final_accepted"))),
            registration_confidence=confidence,
            structural_evidence_source=(
                f"DYNAMIC_GEOMETRY:{row['roi_mode']}" if confidence is not None else None
            ),
            wrong_crop_suspected="WRONG_CROP_SUSPECTED" in (
                row.get("candidate_trace", {}).get("reason_codes") or []
            ),
            cross_field_evidence=facts.cross_field_evidence,
        ))
        accepted = decision.disposition in ACCEPTED
        exact = bool(row["exact"])
        is_critical = policy.criticality in {CriticalityLevel.C2, CriticalityLevel.C3}
        wrong += int(not exact)
        accepted_count += int(accepted)
        correct_accepted += int(accepted and exact)
        critical_total += int(is_critical)
        critical_accepted += int(is_critical and accepted)
        correct_critical_accepted += int(is_critical and accepted and exact)
        safe = not exact and decision.disposition in SAFE_REJECTED
        safe_rejections += int(safe)
        if not accepted:
            review_reasons[_review_category(decision.reason_codes)] += 1
        record = {
            "document_id": row["document_id"], "family": row["family"],
            "field_name": row["field_name"], "criticality": policy.criticality.value,
            "truth": row["expected"], "final_value": value, "exact": exact,
            "wrong_final_value": not exact, "safe_rejection": safe,
            "field_decision": decision.model_dump(mode="json"),
        }
        field_decisions.append(record)
        doc_decisions[row["document_id"]].append(decision)
        if not exact and accepted:
            trace = row.get("candidate_trace") or {}
            false_accepts.append({
                **record,
                "raw_primary_value": trace.get("primary_value", row.get("raw_ocr")),
                "normalized_primary_value": trace.get("primary_normalized"),
                "regional_value": trace.get("regional_value"),
                "secondary_value": trace.get("regional_normalized"),
                "selected_candidate": trace.get("selected_raw_value", value),
                "hard_validation_status": facts.status.value,
                "evidence_classes": decision.available_evidence,
                "reason_codes": decision.reason_codes,
                "candidate_confidence": trace.get("selected_confidence", row.get("ocr_confidence")),
                "localization_mode": row["roi_mode"], "roi": row["predicted_bbox"],
                "expected_value_containment": row["truth_containment"],
                "root_cause": _root_cause(row),
            })

    claim_service = ClaimDecisionService.load()
    claims = []
    for document_id, decisions in doc_decisions.items():
        family = by_doc[document_id][0]["family"]
        result = claim_service.decide(ClaimDecisionContext(
            claim_id=document_id, document_family=family, field_decisions=decisions,
            policy_id=claim_service.policy_id, policy_version=claim_service.policy_version,
            dependent_field_groups=(
                [["total_charge", "charges", "charge_amount"]]
                if family == "CMS1500" else
                [["revenue_code", "hcpcs_code", "units", "charges", "charge_amount"]]
            ),
        ))
        claims.append(result.model_dump(mode="json"))

    secondary = []
    for row in rows:
        trace = row.get("candidate_trace") or {}
        if not trace.get("secondary_invoked"):
            continue
        primary_correct = _canonical(trace.get("primary_normalized")) == _canonical(row["expected"])
        secondary_correct = _canonical(trace.get("regional_normalized")) == _canonical(row["expected"])
        secondary.append({
            "document_id": row["document_id"], "family": row["family"],
            "field_name": row["field_name"], "primary_candidate": trace.get("primary_value"),
            "primary_validation": trace.get("primary_accepted"), "primary_correct": primary_correct,
            "secondary_candidate": trace.get("regional_value"),
            "secondary_validation": trace.get("regional_accepted"),
            "secondary_correct": secondary_correct,
            "selected_candidate": trace.get("selected_raw_value"),
            "changed_output": trace.get("changed_output", False),
            "fixed_an_error": secondary_correct and not primary_correct and row["exact"],
            "introduced_an_error": primary_correct and not row["exact"],
            "avoided_review": secondary_correct and not primary_correct,
            "added_latency_ms": None,
        })

    review_fields = sum(
        record["field_decision"]["disposition"] not in {item.value for item in ACCEPTED}
        for record in field_decisions
    )
    blocking_review = sum(
        record["field_decision"]["blocks_stp"] and
        record["field_decision"]["disposition"] not in {item.value for item in ACCEPTED}
        for record in field_decisions
    )
    critical_review = sum(
        record["criticality"] in {"C2", "C3"} and
        record["field_decision"]["disposition"] not in {item.value for item in ACCEPTED}
        for record in field_decisions
    )
    stp = sum(claim["stp_eligible"] for claim in claims)
    reviewed_claims = len(claims)-stp
    perfect = sum(all(row["exact"] for row in values) for values in by_doc.values())
    single_blocker = sum(len(claim["blocking_unresolved_fields"]) == 1 for claim in claims)
    blocking_total = sum(record["field_decision"]["blocks_stp"] for record in field_decisions)
    noncritical_total = sum(record["criticality"] not in {"C2", "C3"} for record in field_decisions)
    noncritical_review = sum(
        record["criticality"] not in {"C2", "C3"} and
        record["field_decision"]["disposition"] not in {item.value for item in ACCEPTED}
        for record in field_decisions
    )
    claims_with_blocking_review = sum(bool(claim["blocking_unresolved_fields"]) for claim in claims)
    blockers = Counter(
        field for claim in claims for field in claim["blocking_unresolved_fields"]
    )
    unlock = Counter(
        claim["blocking_unresolved_fields"][0]
        for claim in claims if len(claim["blocking_unresolved_fields"]) == 1
    )
    hitl = {
        "eligible_fields": len(rows), "review_fields": review_fields,
        "field_hitl_rate": review_fields/len(rows),
        "blocking_eligible_fields": blocking_total,
        "blocking_field_hitl_rate": blocking_review/max(1, blocking_total),
        "critical_field_hitl_rate": critical_review/max(1, critical_total),
        "noncritical_field_hitl_rate": noncritical_review/max(1, noncritical_total),
        "review_fields_per_page": review_fields/len(by_doc),
        "review_fields_per_document": review_fields/len(by_doc),
        "claims_with_any_review": reviewed_claims,
        "claims_with_blocking_review": claims_with_blocking_review,
        "claim_hitl_rate": reviewed_claims/len(claims),
        "reason_pareto": dict(review_reasons),
    }
    stp_metrics = {
        "claims": len(claims), "stp_claims": stp, "claim_stp_rate": stp/len(claims),
        "perfect_documents": perfect, "perfect_document_rate": perfect/len(claims),
        "single_blocker_claims": single_blocker,
        "multi_blocker_claims": sum(len(claim["blocking_unresolved_fields"]) > 1 for claim in claims),
        "claim_dispositions": dict(Counter(claim["disposition"] for claim in claims)),
        "claims_blocked_by_field": dict(blockers),
        "claim_unlock_value": dict(unlock),
    }
    safe_coverage = {
        "safe_field_coverage": correct_accepted/len(rows),
        "accepted_field_precision": correct_accepted/max(1, accepted_count),
        "accepted_critical_precision": (
            correct_critical_accepted/critical_accepted if critical_accepted else None
        ),
        "accepted_critical_fields": critical_accepted,
        "accepted_fields": accepted_count, "correct_accepted_fields": correct_accepted,
        "wrong_final_values": wrong, "false_accepts": len(false_accepts),
        "false_accept_rate": len(false_accepts)/len(rows), "safe_rejections": safe_rejections,
    }
    for dimension, key in (("family", "coverage_by_family"), ("field_name", "coverage_by_field")):
        grouped = defaultdict(list)
        for record in field_decisions:
            grouped[record[dimension]].append(record)
        safe_coverage[key] = {
            name: {
                "eligible": len(values),
                "correct_accepted": sum(
                    item["exact"] and item["field_decision"]["disposition"] in
                    {accepted.value for accepted in ACCEPTED} for item in values
                ),
                "safe_coverage": sum(
                    item["exact"] and item["field_decision"]["disposition"] in
                    {accepted.value for accepted in ACCEPTED} for item in values
                ) / len(values),
            }
            for name, values in sorted(grouped.items())
        }
    secondary_metrics = {
        "calls": len(secondary), "invocation_rate": len(secondary)/len(rows),
        "resolution_rate": sum(item["fixed_an_error"] for item in secondary)/max(1, len(secondary)),
        "accuracy_gain": sum(item["fixed_an_error"] for item in secondary)/len(rows),
        "false_resolution_rate": sum(item["introduced_an_error"] for item in secondary)/max(1, len(secondary)),
        "regression_count": sum(item["introduced_an_error"] for item in secondary),
        "review_avoidance": sum(item["avoided_review"] for item in secondary),
        "calls_per_page": len(secondary)/len(by_doc), "records": secondary,
    }

    # Preserve the nine Phase 8.1 extraction-level false-accept cases as the
    # remediation audit set even though the final canonical replay rejects
    # them safely. Final canonical false accepts remain a separate artifact.
    baseline_case_rows = []
    baseline_path = output / "golden_cached/field_records.jsonl"
    if baseline_path.is_file():
        final_by_key = {
            (item["document_id"], item["field_name"]): item for item in field_decisions
        }
        for baseline_row in (
            json.loads(line) for line in baseline_path.read_text("utf-8").splitlines()
        ):
            if not baseline_row.get("false_accept"):
                continue
            trace = baseline_row.get("candidate_trace") or {}
            current = final_by_key.get((baseline_row["document_id"], baseline_row["field_name"]))
            baseline_case_rows.append({
                "document_id": baseline_row["document_id"],
                "family": baseline_row["family"], "field": baseline_row["field_name"],
                "criticality": "critical" if baseline_row.get("critical") else "noncritical",
                "truth": baseline_row["expected"],
                "raw_primary_value": trace.get("primary_value", baseline_row.get("raw_ocr")),
                "normalized_primary_value": trace.get("primary_normalized"),
                "regional_value": trace.get("regional_value"),
                "secondary_value": trace.get("regional_normalized"),
                "selected_candidate": trace.get("selected_raw_value"),
                "baseline_final_value": baseline_row.get("final"),
                "baseline_hard_validation_status": trace.get("validation_status"),
                "baseline_extraction_accept": True,
                "final_canonical_disposition": (
                    current["field_decision"]["disposition"] if current else None
                ),
                "final_reason_codes": current["field_decision"]["reason_codes"] if current else [],
                "candidate_confidence": trace.get("selected_confidence"),
                "localization_mode": baseline_row.get("roi_mode"),
                "roi": baseline_row.get("predicted_bbox"),
                "expected_value_containment": baseline_row.get("truth_containment"),
                "root_cause": _root_cause(baseline_row),
                "remediation_status": "SAFE_REJECTED_BY_CANONICAL_POLICY",
            })

    artifacts = {
        "false_accept_records.json": baseline_case_rows,
        "false_accepts.json": false_accepts,
        "false_accept_pareto.json": {
            "phase8_1_extraction_proxy_cases": len(baseline_case_rows),
            "phase8_1_root_causes": dict(Counter(
                item["root_cause"] for item in baseline_case_rows
            )),
            "final_canonical_false_accepts": len(false_accepts),
            "final_root_causes": dict(Counter(item["root_cause"] for item in false_accepts)),
        },
        "secondary_ocr_value.json": secondary_metrics,
        "field_decisions.jsonl": field_decisions,
        "claim_decisions.jsonl": claims,
        "hitl_metrics.json": hitl,
        "stp_metrics.json": stp_metrics,
        "safe_coverage.json": safe_coverage,
    }
    for name, value in artifacts.items():
        path = output/name
        if name.endswith(".jsonl"):
            path.write_text("\n".join(json.dumps(item) for item in value)+"\n", "utf-8")
        else:
            path.write_text(json.dumps(value, indent=2)+"\n", "utf-8")
    summary = {"hitl": hitl, "stp": stp_metrics, "safe_coverage": safe_coverage,
               "secondary_ocr": {k: v for k, v in secondary_metrics.items() if k != "records"}}
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(analyze(args.input_run, args.output), indent=2))
