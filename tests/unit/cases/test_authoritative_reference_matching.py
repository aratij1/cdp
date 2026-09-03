import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence_decision import DecisionContext, EvidenceDecisionService
from packages.ocr.contracts import OCRCandidate
from packages.reference_data import LocalSnapshotProvider
from packages.reference_enrichment.contracts import (
    ReferenceDecision,
    ReferenceLookupRequest,
    ReferenceRecord,
)
from packages.reference_enrichment.decision_engine import decide, resolve
from packages.reference_enrichment.evidence_adapter import (
    ReferenceEvidenceService,
    reference_evidence_from_decision,
)
from workers.reference_matching import ReferenceMatchingService


def _request(
    field: str,
    candidate: str,
    attributes: dict[str, str],
    identity_key: str = "claim-1",
) -> ReferenceLookupRequest:
    return ReferenceLookupRequest(
        request_id="request-1",
        identity_key=identity_key,
        document_id="document-1",
        page_number=1,
        document_family="CMS1500",
        field_name=field,
        criticality="CRITICAL",
        current_candidate=candidate,
        available_claim_attributes=attributes,
        requested_at=datetime.now(UTC),
        policy_version="reference-v1",
    )


def _record(
    field: str,
    value: str,
    attributes: dict[str, str],
    provider_type: str = "MEMBER",
) -> ReferenceRecord:
    return ReferenceRecord(
        provider_name="approved-local",
        provider_type=provider_type,
        provider_authorized=True,
        dataset_version="2026-08",
        source_record_id="record-1",
        source_lineage=["independent-master"],
        independent_truth=True,
        non_circular_lineage=True,
        reference_attributes=attributes,
        field_values={field: value},
        record_status="ACTIVE",
        response_hash="record-hash",
    )


def test_member_name_correction_does_not_verify_itself() -> None:
    request = _request(
        "patient_last",
        "SM1TH",
        {"member_id": "M-1", "dob": "1980-01-02", "name": "SM1TH"},
    )
    record = _record(
        "patient_last",
        "SMITH",
        {"member_id": "M-1", "dob": "1980-01-02", "name": "SMITH"},
    )
    decision = decide(request, [record])
    assert decision.decision == "REFERENCE_VERIFIED"
    assert "member_id" in decision.matching_attributes
    assert "dob" in decision.matching_attributes


def test_member_id_correction_requires_other_independent_attributes() -> None:
    request = _request(
        "member_id",
        "M-1I",
        {"member_id": "M-1I", "dob": "1980-01-02", "name": "Jane Smith", "zip": "02110"},
    )
    record = _record(
        "member_id",
        "M-11",
        {"member_id": "M-11", "dob": "1980-01-02", "name": "Jane Smith", "zip": "02110"},
    )
    assert decide(request, [record]).decision == "REFERENCE_VERIFIED"
    weak = request.model_copy(update={"available_claim_attributes": {"dob": "1980-01-02"}})
    assert decide(weak, [record]).decision == "INSUFFICIENT_MATCH_ATTRIBUTES"


def test_versioned_code_match_requires_snapshot_provenance() -> None:
    request = _request("cpt_hcpcs", "99213", {"code": "99213"})
    timestamp = datetime.now(UTC)
    record = _record("cpt_hcpcs", "99213", {}, "CPT").model_copy(
        update={"snapshot_timestamp": timestamp, "snapshot_checksum": "sha256:codes"}
    )
    assert decide(request, [record]).decision == "REFERENCE_VERIFIED"
    missing_snapshot = record.model_copy(update={"snapshot_checksum": None})
    result = decide(request, [missing_snapshot])
    assert result.decision == "REFERENCE_CONTRADICTION"
    assert "CODE_SNAPSHOT_PROVENANCE_MISSING" in result.contradictions


def test_resolution_preserves_raw_ocr_and_full_value_lineage() -> None:
    request = _request(
        "patient_last", "SM1TH", {"member_id": "M-1", "dob": "1980-01-02", "name": "SM1TH"}
    )
    record = _record(
        "patient_last", "SMITH", {"member_id": "M-1", "dob": "1980-01-02", "name": "SMITH"}
    )
    resolution = resolve(
        request,
        decide(request, [record]),
        raw_value="Sm1th",
        normalized_value="SM1TH",
    )
    assert resolution.raw_value == "Sm1th"
    assert resolution.normalized_value == "SM1TH"
    assert resolution.reference_candidate == "SMITH"
    assert resolution.corrected_value == "SMITH"
    assert resolution.final_value == "SMITH"


def _snapshot(root: Path, identity_key: str = "claim-1") -> LocalSnapshotProvider:
    records = [
        {
            "identity_key": identity_key,
            "source_record_id": "code-99213",
            "source_lineage": ["licensed-code-snapshot"],
            "reference_attributes": {},
            "field_values": {"cpt_hcpcs": "99213"},
            "record_status": "ACTIVE",
            "response_hash": "record-hash"
        }
    ]
    encoded = json.dumps(records, sort_keys=True).encode()
    (root / "records.json").write_bytes(encoded)
    manifest = {
        "source_name": "test-cpt",
        "reference_domain": "CPT",
        "version": "2026-Q3",
        "snapshot_timestamp": "2026-08-01T00:00:00+00:00",
        "records_sha256": hashlib.sha256(encoded).hexdigest(),
        "authorized": True,
        "independent_truth": True,
        "non_circular_lineage": True,
        "source_contract_id": "test-contract",
        "approved_by": "test-governance",
        "approved_at": "2026-08-01T00:00:00+00:00"
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return LocalSnapshotProvider(root, test_only=False)


def test_local_snapshot_provider_verifies_checksum_and_service_fails_closed(tmp_path: Path) -> None:
    provider = _snapshot(tmp_path)
    request = _request("cpt_hcpcs", "99213", {"code": "99213"})
    service = ReferenceMatchingService([provider])
    accepted = service.match(request, raw_value="99213", normalized_value="99213")
    assert accepted.final_value == "99213"
    assert accepted.decision.evaluation_eligible

    (tmp_path / "records.json").write_text("[]", encoding="utf-8")
    rejected = service.match(request, raw_value="99213", normalized_value="99213")
    assert rejected.final_value == "99213"
    assert rejected.corrected_value is None
    assert rejected.decision.decision == "REFERENCE_PROVIDER_ERROR"


def test_runtime_and_recorded_evaluation_reference_produce_identical_final_decision(
    tmp_path: Path,
) -> None:
    provider = _snapshot(tmp_path, "99213")
    adapter = ReferenceEvidenceService(
        [provider], clock=lambda: datetime(2026, 8, 22, tzinfo=UTC)
    )
    runtime_evidence, provenance = adapter.evidence(
        document_id="document-1", page_number=1, document_family="CMS1500",
        field_name="cpt_hcpcs", criticality=CriticalityLevel.C2,
        raw_value="99213", normalized_value="99213",
        claim_values={"cpt_hcpcs": "99213"},
    )
    assert runtime_evidence is not None and runtime_evidence.verified
    assert provenance is not None
    recorded_evidence = reference_evidence_from_decision(
        ReferenceDecision.model_validate(provenance["decision"])
    )
    candidate = OCRCandidate(
        value="99213", raw_value="99213", engine="paddleocr", model_name="paddleocr",
        model_version="test", preprocessing_variant="raw", raw_confidence=0.99,
        calibrated_confidence=None,
        bounding_box=BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1),
        latency_ms=1,
    )
    service = EvidenceDecisionService()
    common = {
        "field_name": "cpt_hcpcs", "document_family": "CMS1500",
        "criticality": CriticalityLevel.C2, "candidates": [candidate],
        "deterministic_evidence": {"CODE_FORMAT_VALID"}, "hard_validation_passed": True,
    }
    runtime = service.decide(DecisionContext(**common, reference=runtime_evidence))
    evaluation = service.decide(DecisionContext(**common, reference=recorded_evidence))
    assert (
        runtime.disposition, runtime.selected_value, runtime.next_action,
        runtime.reason_codes, runtime.available_evidence, runtime.missing_evidence,
    ) == (
        evaluation.disposition, evaluation.selected_value, evaluation.next_action,
        evaluation.reason_codes, evaluation.available_evidence, evaluation.missing_evidence,
    )


def test_unconfigured_reference_service_explicitly_abstains() -> None:
    evidence, provenance = ReferenceEvidenceService([]).evidence(
        document_id="document-1", page_number=1, document_family="CMS1500",
        field_name="patient_last", criticality=CriticalityLevel.C2,
        raw_value="SM1TH", normalized_value="SM1TH",
        claim_values={"insured_id_number": "M-1", "patient_dob": "1980-01-02"},
    )
    assert evidence is None
    assert provenance is None


def test_default_live_reference_config_is_fail_closed() -> None:
    service = ReferenceEvidenceService.from_config("config/reference_enrichment.yaml")
    assert service.providers == []
    assert service.policy_version == "reference-enrichment-v1"
