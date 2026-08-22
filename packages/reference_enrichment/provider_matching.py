from __future__ import annotations

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord
from packages.reference_enrichment.member_matching import _norm
from packages.validation_rules.npi import is_valid_npi


def match_provider(
    request: ReferenceLookupRequest, record: ReferenceRecord
) -> tuple[list[str], dict[str, float], list[str], bool]:
    claim, ref = request.available_claim_attributes, record.reference_attributes
    npi = _norm(ref.get("npi"))
    if npi and not is_valid_npi(npi):
        return [], {"npi": 0.0}, ["INVALID_NPI"], False
    claim_npi = _norm(claim.get("npi"))
    if not claim_npi or not npi or claim_npi != npi:
        return [], {"npi": 0.0}, ["NPI_MISMATCH_OR_MISSING"], False
    if record.record_status.upper() not in {"ACTIVE", "FINALIZED"}:
        return ["npi"], {"npi": 1.0}, ["PROVIDER_INACTIVE"], False
    return ["npi"], {"npi": 1.0}, [], True
