"""Compare frozen source-only engineering labels with saved OCR; never run OCR."""
from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from evaluation.engineering_review import (
    SCOPE,
    content_hash,
    digest,
    directory,
    labels,
    read_manifest,
)
from evaluation.validation_blockers import classify_validation
from packages.deterministic_evidence import DeterministicEvidenceService
from packages.field_policy import FieldPolicyRegistry


def measure(saved: Path) -> dict:
    manifest = read_manifest()
    path = saved/"raw_execution.local.json"
    before = digest(path)
    if before!=manifest["saved_ocr_sha256"]: raise ValueError("SAVED_OCR_BINDING_CHANGED")
    completed = labels()
    base = {"scope":"ENGINEERING_12_SCAN_ACCURACY", "production_authority":False,
            "labels_completed":len(completed),"expected_labels":21,"ocr_calls":0,
            "saved_ocr_sha256_before":before,"saved_ocr_sha256_after":before}
    truth_path = directory()/"engineering_truth.json"
    if len(completed)!=21 or not truth_path.exists():
        return {**base,"status":"WAITING_FOR_SOURCE_ONLY_LABELS","exact_accuracy":"NOT_EVALUABLE",
                "normalized_accuracy":"NOT_EVALUABLE","critical_accuracy":"NOT_EVALUABLE"}
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    seal = truth.pop("truth_sha256")
    if (content_hash(truth)!=seal or truth.get("scope")!=SCOPE or truth.get("production_authority") is not False
            or truth.get("manifest_sha256")!=manifest["manifest_sha256"] or truth.get("records")!=completed):
        raise ValueError("ENGINEERING_TRUTH_CHANGED")
    reference = {r["field_id"]:r for r in completed}
    raw = json.loads(path.read_text(encoding="utf-8"))
    policy = FieldPolicyRegistry.load()
    validator = DeterministicEvidenceService(as_of_date=date(2026,9,12))
    from evaluation.engineering_attribution import read as read_attribution

    counts: Counter = Counter()
    families: dict[str,Counter] = {}
    blockers = []
    for claim in raw["claims"]:
        events = [e["envelope"]["payload"] for e in claim["events"] if e["topic"]=="claim.validated"]
        for field in claim["fields"]:
            key = content_hash({"field_id":field["field_id"]})
            label = reference[key]
            spec = policy.for_field(events[-1]["form_type"],field["field_name"])
            observed = field["raw_value"]
            normalized = field.get("normalized_value") or observed
            valid = validator.evaluate(spec.canonical_field_name,normalized)
            family = families.setdefault(spec.canonical_field_name,Counter())
            outcome = "EXCLUDED_"+label["state"]
            cause = "UNDETERMINED"
            if label["state"] == "VALUE":
                correct = observed == label["value"]
                outcome = "CORRECT" if correct else "INCORRECT"
                counts["comparable"]+=1; counts["correct"]+=correct; counts["incorrect"]+=not correct
                family["comparable"]+=1; family["correct"]+=correct
                if spec.criticality.value in {"C2","C3"}:
                    counts["critical_comparable"]+=1; counts["critical_correct"]+=correct
                if correct and normalized != label["value"]:
                    cause = "NORMALIZATION_ERROR"
                elif not valid.passed and correct and label["source_validity"] == "VALID":
                    cause = "VALIDATOR_FALSE_REJECT"
                elif not valid.passed and correct and label["source_validity"] == "INVALID":
                    cause = "VALIDATOR_TRUE_REJECT"
                # Mismatch alone does not prove recognition versus localization.
            elif label["state"] in {"UNREADABLE","SOURCE_CONFLICT"}: cause = "SOURCE_UNREADABLE"
            reviewed_cause=read_attribution(key,seal,before)
            if reviewed_cause:
                if reviewed_cause in {"OCR_RECOGNITION_ERROR","OCR_LOCALIZATION_ERROR"} and outcome != "INCORRECT":
                    raise ValueError("CAUSAL_REVIEW_CONTRADICTS_SOURCE_COMPARISON")
                if reviewed_cause in {"VALIDATOR_TRUE_REJECT","VALIDATOR_FALSE_REJECT"} and valid.passed:
                    raise ValueError("CAUSAL_REVIEW_CONTRADICTS_VALIDATION")
                cause=reviewed_cause
            counts[label["state"]]+=1
            counts["source_invalid_fields"] += label["state"] == "VALUE" and label["source_validity"] == "INVALID"
            if cause != "UNDETERMINED": counts[cause]+=1
            elif outcome=="INCORRECT": counts["unattributed_extraction_errors"]+=1
            if not valid.passed:
                if cause == "UNDETERMINED": counts["unattributed_validation_rejects"] += 1
                blockers.append({"field_id":key,"field_type":spec.canonical_field_name,
                    "validation_categories":classify_validation(valid.failure_reasons),
                    "truth_comparison":outcome,"root_cause":cause})
    after = digest(path)
    if after!=before: raise ValueError("SAVED_OCR_CHANGED_DURING_MEASUREMENT")
    return {**base,"status":"MEASURED","truth_sha256":seal,"comparable_fields":counts["comparable"],
            "exact_accuracy":counts["correct"]/counts["comparable"] if counts["comparable"] else "NOT_EVALUABLE",
            "normalized_accuracy":"NOT_EVALUABLE_NO_APPROVED_NORMALIZATION_CONTRACT",
            "critical_accuracy":counts["critical_correct"]/counts["critical_comparable"] if counts["critical_comparable"] else "NOT_EVALUABLE",
            "counts":dict(counts),"by_field_family":{k:dict(v) for k,v in families.items()},
            "recognition_errors_confirmed":counts["OCR_RECOGNITION_ERROR"],
            "recognition_errors":counts["OCR_RECOGNITION_ERROR"] if not counts["unattributed_extraction_errors"] else "NOT_FULLY_ATTRIBUTED",
            "localization_errors_confirmed":counts["OCR_LOCALIZATION_ERROR"],
            "localization_errors":counts["OCR_LOCALIZATION_ERROR"] if not counts["unattributed_extraction_errors"] else "NOT_FULLY_ATTRIBUTED",
            "true_source_invalid_fields":counts["source_invalid_fields"],
            "validator_true_rejects":counts["VALIDATOR_TRUE_REJECT"],
            "validator_false_rejects":counts["VALIDATOR_FALSE_REJECT"],
            "validator_rejects_unattributed":counts["unattributed_validation_rejects"],
            "unreadable_fields":counts["UNREADABLE"], "source_conflict_fields":counts["SOURCE_CONFLICT"],
            "source_absent_fields":counts["NOT_PRESENT"], "blank_fields":counts["BLANK"],
            "validation_failure_diagnostics":blockers,"saved_ocr_sha256_after":after}
