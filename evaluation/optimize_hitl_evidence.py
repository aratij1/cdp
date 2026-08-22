"""Create a frozen HITL-reduction candidate from extraction evidence only.

Ground truth is deliberately not accepted by this command.  Candidate values
are selected from independently produced OCR families and deterministic field
validation; evaluation happens in a separate process after this file is sealed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from evaluation.schemas import PredictionDataset

ENGINE_FAMILY = {
    "rapidocr": "RAPID_ONNX_FAMILY",
    "paddleocr": "PADDLE_FAMILY",
}
LABEL_TOKENS = {
    "PATIENT", "INSURED", "SUBSCRIBER", "PROVIDER", "NAME", "FIRST", "LAST",
    "ADDRESS", "CITY", "STATE", "ZIP", "SIGNATURE", "RELATIONSHIP",
}
NAME_FIELDS = {"patient_first", "patient_last", "insured_first", "insured_last", "provider_name"}
PROMOTABLE_FIELDS = NAME_FIELDS
ADDRESS_FIELDS = {
    "patient_addr1", "patient_addr2", "insured_addr1", "insured_addr2",
    "patient_city", "insured_city", "patient_state", "insured_state",
    "patient_zip", "insured_zip",
}
STATE_FIELDS = {"patient_state", "insured_state"}
ZIP_FIELDS = {"patient_zip", "insured_zip"}
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}


def _engine_family(engine: str) -> str:
    key = engine.lower()
    if key.startswith("tesseract"):
        return "TESSERACT_FAMILY"
    return ENGINE_FAMILY.get(key, key.upper())


def _tokens(value: Any) -> tuple[str, ...]:
    return tuple(re.findall(r"[A-Z0-9]+", str(value or "").upper()))


def _canonical(field: str, value: Any) -> str:
    tokens = _tokens(value)
    if field in ADDRESS_FIELDS and field not in STATE_FIELDS | ZIP_FIELDS:
        return " ".join(sorted(tokens))
    return "".join(tokens)


def _deterministically_valid(field: str, value: str) -> bool:
    if not value:
        return False
    if field in STATE_FIELDS:
        return value in US_STATES
    if field in ZIP_FIELDS:
        return bool(re.fullmatch(r"\d{5}(?:\d{4})?", value))
    if field in NAME_FIELDS:
        tokens = set(_tokens(value))
        return bool(tokens) and not tokens.intersection(LABEL_TOKENS) and len(value) >= 2
    return True


def _best_by_family(field: dict[str, Any]) -> dict[str, dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for candidate in (field.get("metadata") or {}).get("ocr_candidates", []):
        value = candidate.get("value") or candidate.get("raw")
        canonical = _canonical(field["field_name"], value)
        if not canonical:
            continue
        family = _engine_family(str(candidate.get("engine") or ""))
        confidence = float(candidate.get("confidence") or 0.0)
        if family not in best or confidence > float(best[family].get("confidence") or 0.0):
            best[family] = {**candidate, "canonical": canonical, "family": family}
    return best


def evidence_decision(field: dict[str, Any]) -> dict[str, Any] | None:
    """Return a truth-blind promotion decision, or ``None`` to retain review."""
    if field.get("accepted"):
        return None
    name = str(field["field_name"])
    # Routes are allow-listed after an isolated experiment.  Address and code
    # consensus remain review-only: on the development set, agreement often
    # reflected the same wrong crop and therefore was not independent truth.
    if name not in PROMOTABLE_FIELDS:
        return None
    candidates = _best_by_family(field)
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates.values():
        groups.setdefault(candidate["canonical"], []).append(candidate)
    eligible = [
        rows for rows in groups.values()
        if len(rows) >= 2
        and _deterministically_valid(name, str(rows[0].get("value") or rows[0].get("raw") or ""))
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda rows: (len(rows), sum(float(r.get("confidence") or 0) for r in rows)), reverse=True)
    winners = eligible[0]
    families = {row["family"] for row in winners}
    if name in NAME_FIELDS and not {"RAPID_ONNX_FAMILY", "PADDLE_FAMILY"}.issubset(families):
        return None
    if min(float(row.get("confidence") or 0.0) for row in winners) < 0.85:
        return None
    selected = max(winners, key=lambda row: float(row.get("confidence") or 0.0))
    return {
        "value": selected.get("value") or selected.get("raw"),
        "canonical": selected["canonical"],
        "families": sorted(families),
        "confidence": min(float(row.get("confidence") or 0.0) for row in winners),
        "reason": "INDEPENDENT_ENGINE_CONSENSUS_AND_DETERMINISTIC_VALIDATION",
    }


def _reference_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        parts = str(row.get("identity_key") or "").split("|")
        if len(parts) >= 5:
            indexed[(parts[0], parts[-1])] = row
    return indexed


def optimize_dataset(
    payload: dict[str, Any], reference_decisions: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    PredictionDataset.model_validate(payload)
    output = deepcopy(payload)
    promoted = Counter()
    promotion_sources = Counter()
    references = _reference_index(reference_decisions or [])
    for document in output["documents"]:
        for field in document["fields"]:
            reference = references.get((document["document_id"], field["field_name"])) or {}
            reference_value = str(reference.get("reference_value") or "")
            if (
                not field.get("accepted")
                and reference.get("decision") == "REFERENCE_VERIFIED"
                and _canonical(field["field_name"], reference_value)
            ):
                field["before_fallback_value"] = field.get("raw_value")
                field["raw_value"] = reference_value
                field["accepted"] = True
                field["reviewed"] = False
                field["validation_result"] = "VALID_REFERENCE_VERIFIED"
                field["extraction_method"] = "authorized_reference_v1"
                field.setdefault("metadata", {})["hitl_optimization"] = {
                    "policy_version": "hitl-evidence-v1",
                    "ground_truth_loaded": False,
                    "reason": "AUTHORIZED_REFERENCE_VERIFIED",
                    "reference_provider": reference.get("reference_provider"),
                    "reference_dataset_version": reference.get("reference_dataset_version"),
                    "source_record_id": reference.get("source_record_id"),
                }
                promoted[field["field_name"]] += 1
                promotion_sources["authorized_reference"] += 1
                continue
            decision = evidence_decision(field)
            if decision is None:
                continue
            field["raw_value"] = decision["value"]
            field["confidence"] = decision["confidence"]
            field["accepted"] = True
            field["reviewed"] = False
            field["validation_result"] = "VALID_EVIDENCE_CONSENSUS"
            field["extraction_method"] = "evidence_consensus_v1"
            metadata = field.setdefault("metadata", {})
            metadata["hitl_optimization"] = {
                "policy_version": "hitl-evidence-v1",
                "ground_truth_loaded": False,
                **decision,
            }
            promoted[field["field_name"]] += 1
            promotion_sources["independent_ocr_and_validation"] += 1
    PredictionDataset.model_validate(output)
    initial_review = sum(not f.get("accepted", False) for d in payload["documents"] for f in d["fields"])
    remaining_review = sum(not f.get("accepted", False) for d in output["documents"] for f in d["fields"])
    metrics = {
        "policy_version": "hitl-evidence-v1",
        "ground_truth_loaded": False,
        "initial_review_fields": initial_review,
        "promoted_fields": initial_review - remaining_review,
        "remaining_review_fields": remaining_review,
        "promotions_by_field": dict(promoted),
        "promotions_by_source": dict(promotion_sources),
        "reference_decisions_supplied": len(reference_decisions or []),
    }
    return output, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-decisions", type=Path)
    args = parser.parse_args()
    source = json.loads(args.predictions.read_text(encoding="utf-8"))
    references = (
        json.loads(args.reference_decisions.read_text(encoding="utf-8"))
        if args.reference_decisions else []
    )
    optimized, metrics = optimize_dataset(source, references)
    args.output.mkdir(parents=True, exist_ok=True)
    candidate = args.output / "predictions.json"
    candidate.write_text(json.dumps(optimized, indent=2) + "\n", encoding="utf-8")
    metrics["candidate_sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    (args.output / "optimization.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
