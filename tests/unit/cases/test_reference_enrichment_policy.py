from datetime import UTC, datetime

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceRecord
from packages.reference_enrichment.decision_engine import decide, normalize_reference


def request(attributes: dict[str, str], field: str = "patient_last") -> ReferenceLookupRequest:
    return ReferenceLookupRequest(
        request_id="r1",
        identity_key="D|1|CMS1500||patient_last",
        document_id="D",
        page_number=1,
        document_family="CMS1500",
        field_name=field,
        criticality="CRITICAL",
        current_candidate="OCR",
        available_claim_attributes=attributes,
        requested_at=datetime.now(UTC),
        policy_version="v1",
    )


def record(
    attributes: dict[str, str],
    *,
    lineage: list[str] | None = None,
    authorized: bool = True,
    status: str = "ACTIVE",
) -> ReferenceRecord:
    return ReferenceRecord(
        provider_name="member-master",
        provider_type="MEMBER",
        provider_authorized=authorized,
        dataset_version="2026-08",
        source_record_id="M1",
        source_lineage=lineage or ["member-master"],
        independent_truth=True,
        non_circular_lineage=True,
        reference_attributes=attributes,
        field_values={"patient_last": "Smith"},
        record_status=status,
        response_hash="abc",
    )


def test_tier_a_multi_attribute_match_needs_no_second_human_approval() -> None:
    attrs = {"member_id": "M1", "dob": "1980-01-02", "name": "Jane Smith"}
    result = decide(request(attrs), [record(attrs)])
    assert result.decision == "REFERENCE_VERIFIED"
    assert result.evaluation_eligible
    assert result.primary_approved_by == "reference-policy-engine"
    assert result.second_approval_requirement == "NOT_REQUIRED_AUTH_REFERENCE"
    assert result.second_approved_by is None


def test_reference_decision_preserves_snapshot_provenance() -> None:
    attrs = {"member_id": "M1", "dob": "1980-01-02", "name": "Jane Smith"}
    timestamp = datetime.now(UTC)
    governed = record(attrs).model_copy(
        update={"snapshot_timestamp": timestamp, "snapshot_checksum": "sha256:snapshot"}
    )
    result = decide(request(attrs), [governed])
    assert result.snapshot_timestamp == timestamp
    assert result.snapshot_checksum == "sha256:snapshot"


def test_name_only_and_multiple_matches_fail_closed() -> None:
    name = {"name": "Jane Smith"}
    assert decide(request(name), [record(name)]).decision == "INSUFFICIENT_MATCH_ATTRIBUTES"
    assert (
        decide(request(name), [record(name), record(name)]).decision == "MULTIPLE_REFERENCE_MATCHES"
    )


def test_synthetic_provider_is_training_only() -> None:
    attrs = {"member_id": "M1", "dob": "1980-01-02", "name": "Jane Smith"}
    result = decide(request(attrs), [record(attrs)], test_only=True)
    assert result.label_status == "TEST_ONLY"
    assert not result.evaluation_eligible


def test_circular_lineage_and_unauthorized_provider_are_rejected() -> None:
    attrs = {"member_id": "M1", "dob": "1980-01-02", "name": "Jane Smith"}
    circular = record(attrs, lineage=["export", "extraction-v2"])
    assert decide(request(attrs), [circular]).decision == "CIRCULAR_LINEAGE_REJECTED"
    assert (
        decide(request(attrs), [record(attrs, authorized=False)]).decision
        == "PROVIDER_UNAUTHORIZED"
    )


def test_zip_leading_zero_preserved_and_same_rejected() -> None:
    assert normalize_reference("insured_zip", "01234") == ("01234", [])
    assert normalize_reference("insured_addr1", "SAME")[0] is None


def test_invalid_provider_npi_cannot_verify() -> None:
    attrs = {"npi": "1234567890"}
    provider = record(attrs)
    provider = provider.model_copy(update={"field_values": {"provider_npi": "1234567890"}})
    result = decide(request(attrs, "provider_npi"), [provider])
    assert result.decision == "REFERENCE_CONTRADICTION"
    assert "INVALID_NPI" in result.contradictions


def test_missing_dataset_version_blocks_tier_a() -> None:
    attrs = {"member_id": "M1", "dob": "1980-01-02", "name": "Jane Smith"}
    without_version = record(attrs).model_copy(update={"dataset_version": None})
    result = decide(request(attrs), [without_version])
    assert not result.evaluation_eligible


def test_finalized_independent_downstream_requires_verified_mapping() -> None:
    attrs = {
        "member_id": "M1",
        "dob": "1980-01-02",
        "name": "Jane Smith",
        "field_mapping_verified": "true",
    }
    downstream = record(attrs, status="FINALIZED").model_copy(
        update={"provider_type": "FINALIZED_CLAIMS"}
    )
    assert decide(request(attrs), [downstream]).decision == "DOWNSTREAM_VERIFIED"
    unverified = downstream.model_copy(
        update={"reference_attributes": {**attrs, "field_mapping_verified": "false"}}
    )
    assert decide(request(attrs), [unverified]).decision == "REFERENCE_CONTRADICTION"


def test_critical_correction_requires_distinct_second_approver() -> None:
    attrs = {
        "member_id": "M1",
        "dob": "1980-01-02",
        "name": "Jane Smith",
        "primary_approved_by": "reviewer-1",
        "primary_approved_at": "2026-08-01T10:00:00+00:00",
        "second_approved_by": "reviewer-1",
        "second_approved_at": "2026-08-01T11:00:00+00:00",
        "claim_revalidated": "true",
    }
    correction = record(attrs).model_copy(update={"provider_type": "APPROVED_CORRECTION"})
    assert decide(request(attrs), [correction]).decision == "REFERENCE_CONTRADICTION"
    distinct = correction.model_copy(
        update={"reference_attributes": {**attrs, "second_approved_by": "reviewer-2"}}
    )
    assert decide(request(attrs), [distinct]).decision == "CORRECTION_VERIFIED"
