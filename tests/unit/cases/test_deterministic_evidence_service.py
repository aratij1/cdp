from datetime import date

from packages.deterministic_evidence import DeterministicEvidenceService


def test_npi_requires_checksum_not_just_ten_digits():
    service = DeterministicEvidenceService()
    assert service.evaluate("billing_provider_npi", "1234567893").passed
    failed = service.evaluate("billing_provider_npi", "1234567890")
    assert not failed.passed
    assert failed.failure_reasons == ["CHECKSUM_FAILURE"]


def test_amount_and_service_line_sum_create_e4_and_e6():
    result = DeterministicEvidenceService().evaluate(
        "total_charge", "150.00", claim_values={"service_line_charges": "100.00,50.00"}
    )
    assert result.passed
    assert "FORMAT_VALID" in result.evidence
    assert result.cross_field_evidence == {"CLAIM_TOTAL_CONFIRMED"}


def test_date_relationship_is_truth_blind_and_deterministic():
    result = DeterministicEvidenceService().evaluate(
        "patient_dob", "1990-01-01", claim_values={"service_date": "2025-01-01"}
    )
    assert result.passed
    assert "DATE_RELATIONSHIP_CONFIRMED" in result.cross_field_evidence


def test_label_contamination_does_not_create_e4():
    result = DeterministicEvidenceService().evaluate("patient_name", "Patient Name")
    assert not result.passed
    assert "LABEL_CONTAMINATION" in result.failure_reasons


def test_evaluation_as_of_date_is_injectable_without_changing_runtime_default():
    frozen = DeterministicEvidenceService(as_of_date=date(2027, 12, 31))
    assert frozen.evaluate("service_date", "2027-12-25").passed
    assert not frozen.evaluate("service_date", "2028-01-01").passed
