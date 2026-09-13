"""Value-free fingerprints for decisions over persisted extraction state.

Decisions remain durably stored in the transactional outbox. A null selection
on an unresolved decision is not a replacement for the persisted OCR value.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic_core import to_jsonable_python

from packages.domain.extraction import ExtractedField
from packages.evidence_decision import FieldDecision, FieldDisposition

STALE_REASON = "FIELD_DECISION_STALE_RECOMPUTE_REQUIRED"
ACCEPTED = {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED,
            FieldDisposition.HUMAN_CONFIRMED}


def canonical(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): canonical(item) for key,item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((canonical(item) for item in value), key=lambda item: json.dumps(item,sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return to_jsonable_python(value)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode()).hexdigest()


def runtime_digest(pipeline_version: str) -> str:
    root = Path(__file__).resolve().parents[1]
    files = {p.relative_to(root).as_posix(): hashlib.sha256(
        p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for directory in ("packages", "workers", "config")
        for p in (root / directory).rglob("*")
        if p.is_file() and p.suffix in {".py", ".yaml", ".json"}}
    return digest({"pipeline_version": pipeline_version, "implementation": files})


def bind_decision(field: ExtractedField, decision: FieldDecision, *, runtime: str,
                  policy: dict, identity: dict) -> dict[str, str]:
    evidence = [item.model_dump(mode="json") for item in field.candidates]
    selected = [item for item in evidence if item["raw_text"] == field.raw_value]
    return {
        "field_id": str(field.field_id),
        "raw_value_hash": digest(field.raw_value),
        "normalized_value_hash": digest(field.normalized_value),
        "selected_evidence_hash": digest(selected),
        "evidence_hash": digest(evidence),
        "extraction_hash": digest({"field_name": field.field_name,
            "confidence": field.confidence, "page_number": field.page_number,
            "bbox": field.bounding_box.model_dump(mode="json"),
            "method": field.extraction_method.value, "model": field.model_name,
            "version": field.model_version, "reference": field.reference_evidence}),
        "runtime_sha256": runtime, "decision_policy_hash": digest(policy),
        "identity_hash": digest(identity),
        "decision_hash": digest(decision.model_dump(mode="python", exclude={"input_binding"})),
    }


def decision_matches(field: ExtractedField, decision: FieldDecision, *, runtime: str,
                     policy: dict, identity: dict) -> bool:
    expected = bind_decision(field, decision, runtime=runtime, policy=policy, identity=identity)
    value = field.normalized_value or field.raw_value
    selection_matches = (decision.selected_value == value or
        (decision.selected_value is None and decision.disposition not in ACCEPTED))
    return (bool(decision.input_binding) and decision.input_binding == expected
            and decision.field_id == str(field.field_id)
            and decision.field_name == field.field_name
            and decision.disposition.value == field.disposition and selection_matches)
