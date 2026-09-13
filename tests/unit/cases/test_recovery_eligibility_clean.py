from types import SimpleNamespace

import pytest
from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ExtractionMethod
from packages.domain.extraction import FieldEvidence
from packages.templates.cms1500_boxes import ocr_regions, regions
from packages.validation_rules.npi import is_valid_npi
from tests.unit.cases.test_cms1500_template_first import OCR, template
from workers.standard_form_extraction.extractor import StandardFormExtractionService
from workers.standard_form_extraction.recovery_eligibility import assess_recovery


def evidence(raw, tokens=()):
    return FieldEvidence(source=ExtractionMethod.REGIONAL_RAPIDOCR, raw_text=raw,
        confidence=.95, bounding_box=BoundingBox(x0=0,y0=0,x1=100,y1=20,image_width=100,image_height=20), tokens=tokens)


def test_truncated_name_is_eligible():
    assert assess_recovery("patient_name", "text", evidence("DOE,")).eligible


def test_label_contamination_is_eligible():
    token={"text":"PATIENT","bounding_box":{"x0":1,"y0":1,"x1":20,"y1":10}}
    result=assess_recovery("patient_name", "text", evidence("PATIENT", (token,)))
    assert result.eligible and "LABEL_CONTAMINATION" in result.reasons


def test_checksum_invalid_npi_is_eligible():
    invalid=next(value for value in ("1234567890","1111111111") if not is_valid_npi(value))
    result=assess_recovery("provider_npi", "npi", evidence(invalid))
    assert result.eligible and "CHECKSUM_INVALID" in result.reasons


def test_complete_tax_id_does_not_trigger_recovery():
    assert not assess_recovery("federal_tax_no", "tax_id", evidence("123456789")).eligible


def test_recovery_preserves_primary_and_alternative():
    t=template();c=regions(t)["federal_tax_no"][0];e=ocr_regions(t)["federal_tax_no"][0]
    engine=OCR({(c.x0,c.y0,c.x1,c.y1):"123",(e.x0,e.y0,e.x1,e.y1):"123456789"})
    fields=StandardFormExtractionService(engine).extract_cms1500_fields(Image.new("RGB",(1712,2214)),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    field=next(item for item in fields if item.field_name=="federal_tax_no")
    assert field.raw_value=="123456789" and len(field.candidates)>=2


@pytest.mark.parametrize("original,recovered", [
    ("DOE,", ""),
    ("DOE,", "PATIENT NAME"),
    ("DOE,", "SMITH,"),
])
def test_suspicious_expansion_preserves_original_and_both_crop_evidence(original, recovered):
    field = extract_name_pair(original, recovered)
    assert field.raw_value == original
    assert field.validation_status.value == "NEEDS_REVIEW"
    assert "RECOVERY_UNRESOLVED" in field.validation_reasons
    assert [item.raw_text for item in field.candidates] == [original, recovered]
    assert [item.provenance.preprocessing_version for item in field.candidates] == [
        "CANONICAL_PRIMARY", "BOUNDED_VALUE_RECOVERY",
    ]


def extract_name_pair(original, recovered):
    t = template()
    canonical = regions(t)["patient_name"][0]
    expanded = ocr_regions(t)["patient_name"][0]
    engine = OCR({
        (canonical.x0, canonical.y0, canonical.x1, canonical.y1): original,
        (expanded.x0, expanded.y0, expanded.x1, expanded.y1): recovered,
    })
    fields = StandardFormExtractionService(engine).extract_cms1500_fields(
        Image.new("RGB", (1712, 2214)), t, 1,
        SimpleNamespace(authorizes_fixed_roi=True),
    )
    return next(item for item in fields if item.field_name == "patient_name")


def test_clean_expansion_recovers_truncated_name():
    field = extract_name_pair("DOE,", "DOE, JANE")
    assert field.raw_value == "DOE, JANE"
    assert [item.raw_text for item in field.candidates] == ["DOE, JANE", "DOE,"]


@pytest.mark.parametrize("original,recovered", [("PATIENT NAME", "DOE, JANE"), ("DOE,", "DOE, JANE")])
def test_clean_recovery_resolves_suspicion(original, recovered):
    field = extract_name_pair(original, recovered)
    assert field.raw_value == recovered
    assert "RECOVERY_UNRESOLVED" not in field.validation_reasons


def test_equal_confidence_does_not_copy_winning_value_to_rejected_candidate():
    from packages.evidence_decision.adapters import ocr_candidates_from_field
    field = extract_name_pair("DOE,", "DOE, JANE")
    candidates = ocr_candidates_from_field(field)
    assert candidates[0].value == field.normalized_value
    assert candidates[1].value == "DOE,"


@pytest.mark.parametrize("recovery,expected,unresolved", [
    ("1234567893", "1234567893", False), ("1111111111", "", True),
])
def test_npi_checksum_recovery(recovery, expected, unresolved):
    t = template()
    c = regions(t)["provider_npi"][0]
    e = ocr_regions(t)["provider_npi"][0]
    engine = OCR({(c.x0,c.y0,c.x1,c.y1): "1234567890", (e.x0,e.y0,e.x1,e.y1): recovery})
    fields = StandardFormExtractionService(engine).extract_cms1500_fields(
        Image.new("RGB", (1712,2214)), t, 1, SimpleNamespace(authorizes_fixed_roi=True))
    field = next(f for f in fields if f.field_name == "provider_npi")
    assert field.raw_value == expected
    assert ("RECOVERY_UNRESOLVED" in field.validation_reasons) == unresolved
    assert {"1234567890", recovery}.issubset({c.raw_text for c in field.candidates})


def test_unresolved_recovery_cannot_become_reference_confirmed():
    from dataclasses import replace

    from packages.evidence_decision import ReferenceEvidence
    from packages.evidence_decision.contracts import FieldDisposition
    from packages.evidence_decision.service import EvidenceDecisionService
    from tests.unit.cases.test_evidence_decision_service import candidate, context
    item = replace(candidate("rapidocr", "JANE DOE"), validation_results=("RECOVERY_UNRESOLVED",))
    decision = EvidenceDecisionService(route_mode="evaluation").decide(context(
        candidates=[item], registration_confidence=.99,
        reference=ReferenceEvidence(value="JANE DOE", verified=True, source="eligibility", version="test"),
        reference_source_state="AUTHORIZED", cross_field_evidence={"IDENTITY_RECONCILED"},
    ))
    assert decision.disposition == FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert "RECOVERY_UNRESOLVED" in decision.reason_codes


@pytest.mark.parametrize("name,kind,raw", [
    ("principal_diagnosis", "code", "DIAGNOSIS"),
    ("principal_diagnosis", "code", "12345"),
    ("federal_tax_no", "tax_id", "NPI 123456789"),
    ("total_charge", "currency", "12.345"),
    ("patient_dob", "date", "02/30/2000"),
])
def test_structurally_invalid_values_require_recovery(name, kind, raw):
    assert assess_recovery(name, kind, evidence(raw)).eligible


@pytest.mark.parametrize("name,kind,raw", [
    ("principal_diagnosis", "code", "A12.3"),
    ("total_charge", "currency", "$1,234.50"),
    ("patient_dob", "date", "02/29/2000"),
])
def test_structurally_valid_values_remain_clean(name, kind, raw):
    assert not assess_recovery(name, kind, evidence(raw)).eligible
