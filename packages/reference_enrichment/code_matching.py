from __future__ import annotations

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord
from packages.reference_enrichment.member_matching import _norm


def match_code(
    request: ReferenceLookupRequest, record: ReferenceRecord
) -> tuple[list[str], dict[str, float], list[str], bool]:
    candidate = _norm(request.current_candidate or request.available_claim_attributes.get("code"))
    reference = _norm(record.field_values.get(request.field_name))
    if not candidate or not reference:
        return [], {"code": 0.0}, ["CODE_MISSING"], False
    if candidate != reference:
        return [], {"code": 0.0}, ["CODE_NOT_IN_REFERENCE_SNAPSHOT"], False
    if record.record_status.upper() not in {"ACTIVE", "VALID"}:
        return ["code"], {"code": 1.0}, ["CODE_INACTIVE"], False
    if not record.dataset_version or not record.snapshot_timestamp or not record.snapshot_checksum:
        return ["code"], {"code": 1.0}, ["CODE_SNAPSHOT_PROVENANCE_MISSING"], False
    return ["code"], {"code": 1.0}, [], True
