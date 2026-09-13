from types import SimpleNamespace

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
