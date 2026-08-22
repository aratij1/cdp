from __future__ import annotations

from difflib import SequenceMatcher

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord


def _norm(value: str | None) -> str:
    return "".join(char for char in (value or "").upper() if char.isalnum())


def match_member(
    request: ReferenceLookupRequest, record: ReferenceRecord
) -> tuple[list[str], dict[str, float], list[str], bool]:
    claim = request.available_claim_attributes
    ref = record.reference_attributes
    matched: list[str] = []
    contradictions: list[str] = []
    scores: dict[str, float] = {}
    target_attribute = (
        "member_id"
        if request.field_name in {"member_id", "insured_id_number"}
        else "dob"
        if request.field_name in {"dob", "patient_dob"}
        else "name"
        if request.field_name in {"patient_name", "patient_first", "patient_last"}
        else "zip"
        if request.field_name.endswith("_zip") or "address" in request.field_name
        else None
    )
    for key in ("member_id", "dob", "zip"):
        left, right = _norm(claim.get(key)), _norm(ref.get(key))
        if left and right:
            scores[key] = float(left == right)
            if left == right:
                matched.append(key)
            elif key != target_attribute:
                contradictions.append(key)
    left_name, right_name = _norm(claim.get("name")), _norm(ref.get("name"))
    if left_name and right_name:
        scores["name"] = SequenceMatcher(None, left_name, right_name).ratio()
        if scores["name"] >= 0.92:
            matched.append("name")
        elif target_attribute != "name":
            contradictions.append("name")
    member_dob = (
        target_attribute != "member_id"
        and scores.get("member_id") == 1
        and scores.get("dob") == 1
    )
    fallback = scores.get("dob") == 1 and scores.get("name", 0) >= 0.92 and scores.get("zip") == 1
    return matched, scores, contradictions, bool((member_dob or fallback) and not contradictions)
