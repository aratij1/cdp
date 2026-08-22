from packages.field_verification import repair_npi_missing_leading_digit, verify_field
from evaluation.generate_public_synthetic_claims import _valid_npi


def test_checksum_valid_npi_requires_independent_agreement_for_auto_verification():
    npi = _valid_npi(42)
    assert verify_field("provider_npi", npi).auto_verifiable is False
    evidence = verify_field("provider_npi", npi, independent_agreement=2)
    assert evidence.valid
    assert evidence.strength == "CHECKSUM"
    assert evidence.auto_verifiable


def test_syntax_only_code_is_never_treated_as_truth():
    evidence = verify_field("principal_diagnosis", "A12.3", independent_agreement=2)
    assert evidence.valid
    assert evidence.strength == "SYNTAX"
    assert not evidence.auto_verifiable


def test_invalid_npi_is_rejected_even_when_engines_agree():
    evidence = verify_field("provider_npi", "1234567890", independent_agreement=2)
    assert not evidence.valid
    assert not evidence.auto_verifiable


def test_missing_leading_npi_digit_is_repaired_only_by_unique_checksum():
    npi = _valid_npi(42)
    assert repair_npi_missing_leading_digit(npi[1:]) == npi
    assert repair_npi_missing_leading_digit(npi) is None
