"""Deterministic validators: NPI Luhn, ICD-10/CPT/HCPCS syntax, dates,
reconciliation, thresholds, and the engine tying them together.

NPI/ICD-10/CPT test vectors are cross-checked against the real dataset
(requires_dataset-gated) in addition to synthetic examples -- see
docs/DATASET_FINDINGS.md.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from packages.domain.claim import Claim, ServiceLine
from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType, ExtractionMethod, FieldCriticality
from packages.domain.extraction import ExtractedField
from packages.templates.models import Template
from packages.validation_rules.cpt_hcpcs import (
    is_valid_cpt_syntax,
    is_valid_hcpcs_syntax,
    is_valid_modifier_syntax,
)
from packages.validation_rules.dates import (
    check_birth_date_precedes_service_date,
    check_not_future,
    check_range_order,
)
from packages.validation_rules.engine import ValidationEngine
from packages.validation_rules.icd10 import is_valid_icd10_syntax
from packages.validation_rules.npi import is_valid_npi
from packages.validation_rules.numeric import check_non_negative_currency, check_positive_units
from packages.validation_rules.reconciliation import check_service_line_total_matches_claim_total
from packages.validation_rules.required_fields import find_missing_required_fields
from packages.validation_rules.thresholds import FieldThreshold, ThresholdRegistry
from tests.conftest import requires_dataset

# --- NPI ---------------------------------------------------------------


def test_valid_npi_passes_luhn_checksum():
    assert is_valid_npi("1234567893")  # widely-cited valid test NPI


def test_invalid_npi_fails_checksum():
    assert not is_valid_npi("1234567890")


def test_npi_requires_exactly_ten_digits():
    assert not is_valid_npi("123")
    assert not is_valid_npi("12345678901")
    assert not is_valid_npi("123456789A")


@requires_dataset
def test_real_provider_npi_from_dataset_is_valid(dataset_raw_dir):
    """The NPI printed on the real sample CMS-1500 (and stored in the NSF
    BA0 record) is a genuinely assigned NPI -- it must pass the checksum."""
    with open(dataset_raw_dir / "Group A" / "DATAMATICS_UBH_HCFA_07212026 - Group A.txt", "rb") as f:
        lines = f.read().decode("ascii").split("\r\n")
    ba0 = next(line for line in lines if line.startswith("BA0"))
    npi = ba0[47:62].strip()  # provider_medicare_number, positions 48-62
    assert is_valid_npi(npi)


# --- ICD-10 --------------------------------------------------------------


@pytest.mark.parametrize("code", ["G31.84", "F02.81", "F20.9", "E11.9", "A00", "Z0000"])
def test_valid_icd10_codes(code):
    assert is_valid_icd10_syntax(code)


@pytest.mark.parametrize("code", ["U07.1", "12345", "GG31.84", "G3184.", ""])
def test_invalid_icd10_codes(code):
    assert not is_valid_icd10_syntax(code)


# --- CPT/HCPCS -----------------------------------------------------------


@pytest.mark.parametrize("code", ["96116", "96132", "96133", "96136", "96137"])
def test_real_cpt_codes_from_dataset_are_valid(code):
    """CPT codes as they literally appear on the real sample CMS-1500."""
    assert is_valid_cpt_syntax(code)
    assert is_valid_hcpcs_syntax(code)


def test_hcpcs_level_ii_syntax():
    assert is_valid_hcpcs_syntax("J1234")
    assert not is_valid_hcpcs_syntax("12345A")


def test_modifier_syntax():
    assert is_valid_modifier_syntax("25")
    assert is_valid_modifier_syntax("LT")
    assert not is_valid_modifier_syntax("ABC")


# --- dates -----------------------------------------------------------------


def test_check_not_future():
    assert check_not_future(date(2020, 1, 1), today=date(2025, 1, 1)).ok
    assert not check_not_future(date(2030, 1, 1), today=date(2025, 1, 1)).ok


def test_check_range_order():
    assert check_range_order(date(2025, 1, 1), date(2025, 1, 2)).ok
    assert not check_range_order(date(2025, 1, 2), date(2025, 1, 1)).ok


def test_birth_date_must_precede_service_date():
    result = check_birth_date_precedes_service_date(date(1990, 1, 1), date(2025, 1, 1))
    assert result.ok
    result = check_birth_date_precedes_service_date(date(2030, 1, 1), date(2025, 1, 1))
    assert not result.ok


# --- numeric -----------------------------------------------------------------


def test_currency_and_units_checks():
    assert check_non_negative_currency(Decimal("175.00")).ok
    assert not check_non_negative_currency(Decimal("-1.00")).ok
    assert check_positive_units(Decimal(1)).ok
    assert not check_positive_units(Decimal(0)).ok


# --- required fields -----------------------------------------------------------------


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100)


def _field(name: str, raw: str) -> ExtractedField:
    return ExtractedField(
        field_name=name,
        raw_value=raw,
        normalized_value=raw,
        confidence=0.95,
        page_number=1,
        bounding_box=_bbox(),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
    )


def test_find_missing_required_fields():
    fields = [_field("patient_name", "DOE JOHN"), _field("total_charge", "")]
    missing = find_missing_required_fields(["patient_name", "total_charge", "federal_tax_id"], fields)
    assert missing == ["total_charge", "federal_tax_id"]


# --- reconciliation -----------------------------------------------------------------


def _claim(total_charge, service_lines) -> Claim:
    return Claim(
        document_id=uuid4(),
        tenant_id="t1",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1.0",
        total_charge_amount=total_charge,
        service_lines=service_lines,
    )


def test_reconciliation_passes_when_totals_match():
    lines = [
        ServiceLine(line_number=1, charge_amount=Decimal("150.00")),
        ServiceLine(line_number=2, charge_amount=Decimal("25.00")),
    ]
    claim = _claim(Decimal("175.00"), lines)
    result = check_service_line_total_matches_claim_total(claim)
    assert result.ok


def test_reconciliation_fails_when_totals_disagree():
    lines = [ServiceLine(line_number=1, charge_amount=Decimal("150.00"))]
    claim = _claim(Decimal("999.00"), lines)
    result = check_service_line_total_matches_claim_total(claim)
    assert not result.ok
    assert "150.00" in result.reason


def test_reconciliation_fails_when_total_charge_missing():
    claim = _claim(None, [ServiceLine(line_number=1, charge_amount=Decimal("1.00"))])
    result = check_service_line_total_matches_claim_total(claim)
    assert not result.ok


# --- thresholds -----------------------------------------------------------------


def test_threshold_registry_uses_configured_value():
    registry = ThresholdRegistry(
        [FieldThreshold(field_name="npi", criticality=FieldCriticality.CRITICAL, min_confidence=0.99)]
    )
    assert registry.min_confidence_for("npi") == 0.99
    assert not registry.meets_threshold("npi", 0.9)
    assert registry.meets_threshold("npi", 0.995)


def test_threshold_registry_falls_back_to_criticality_defaults():
    registry = ThresholdRegistry([])
    assert registry.min_confidence_for("anything", FieldCriticality.CRITICAL) == 0.90
    assert registry.min_confidence_for("anything", FieldCriticality.NON_CRITICAL) == 0.70


# --- engine (end-to-end) -----------------------------------------------------------------


def _minimal_cms1500_template() -> Template:
    from packages.templates import TemplateRegistry
    from packages.templates.registry import DEFAULT_TEMPLATE_DIR

    return TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR).get("cms1500", "02-12")


def test_engine_flags_missing_required_field():
    registry = ThresholdRegistry([])
    engine = ValidationEngine(registry)
    template = _minimal_cms1500_template()
    claim = Claim(
        document_id=uuid4(),
        tenant_id="t1",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1.0",
        header_fields=[],
    )
    results = engine.validate_claim(claim, template)
    missing_names = {r.field_name for r in results if r.rule_name == "required_field"}
    assert "insured_id_number" in missing_names


def test_engine_flags_invalid_npi_and_valid_reconciliation():
    registry = ThresholdRegistry.load_from_directory()
    engine = ValidationEngine(registry)
    template = _minimal_cms1500_template()

    npi_field = ExtractedField(
        field_name="rendering_provider_npi",
        raw_value="1234567890",
        normalized_value="1234567890",  # fails Luhn
        confidence=0.99,
        page_number=1,
        bounding_box=_bbox(),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
    )
    line = ServiceLine(line_number=1, charge_amount=Decimal("100.00"))
    claim = Claim(
        document_id=uuid4(),
        tenant_id="t1",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1.0",
        header_fields=[npi_field],
        service_lines=[line],
        total_charge_amount=Decimal("100.00"),
    )

    results = engine.validate_claim(claim, template)
    npi_results = [r for r in results if r.rule_name == "npi_luhn_checksum"]
    assert len(npi_results) == 1
    assert npi_results[0].status.value == "INVALID"

    recon_results = [r for r in results if r.rule_name == "service_line_total_reconciliation"]
    assert recon_results[0].status.value == "VALID"


def test_engine_flags_low_confidence_critical_field_for_review():
    registry = ThresholdRegistry(
        [
            FieldThreshold(
                field_name="total_charge",
                criticality=FieldCriticality.CRITICAL,
                min_confidence=0.95,
            )
        ]
    )
    engine = ValidationEngine(registry)
    template = _minimal_cms1500_template()

    low_confidence_field = ExtractedField(
        field_name="total_charge",
        raw_value="175.00",
        normalized_value="175.00",
        confidence=0.5,
        page_number=1,
        bounding_box=_bbox(),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
    )
    claim = Claim(
        document_id=uuid4(),
        tenant_id="t1",
        correlation_id=uuid4(),
        form_type=ClaimFormType.CMS1500,
        schema_version="1.0",
        header_fields=[low_confidence_field],
        total_charge_amount=Decimal("175.00"),
    )

    results = engine.validate_claim(claim, template)
    review_results = [r for r in results if r.rule_name == "confidence_threshold"]
    assert len(review_results) == 1
    assert review_results[0].status.value == "NEEDS_REVIEW"
