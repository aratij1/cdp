from __future__ import annotations

from difflib import SequenceMatcher

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord
from packages.reference_enrichment.member_matching import _norm


def match_payer(
    request: ReferenceLookupRequest, record: ReferenceRecord
) -> tuple[list[str], dict[str, float], list[str], bool]:
    claim, ref = request.available_claim_attributes, record.reference_attributes
    claim_id, ref_id = _norm(claim.get("payer_id")), _norm(ref.get("payer_id"))
    if not claim_id or not ref_id or claim_id != ref_id:
        return [], {"payer_id": 0.0}, ["PAYER_ID_MISMATCH_OR_MISSING"], False
    matched = ["payer_id"]
    scores = {"payer_id": 1.0}
    claim_name, ref_name = _norm(claim.get("payer_name")), _norm(ref.get("payer_name"))
    if claim_name and ref_name:
        scores["payer_name"] = SequenceMatcher(None, claim_name, ref_name).ratio()
        if scores["payer_name"] >= 0.90:
            matched.append("payer_name")
    if record.record_status.upper() not in {"ACTIVE", "VALID"}:
        return matched, scores, ["PAYER_INACTIVE"], False
    return matched, scores, [], True
