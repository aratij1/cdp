from types import SimpleNamespace

import pytest
from PIL import Image

from packages.canonical_field_outcomes import canonical_field_outcomes
from packages.templates.cms1500_boxes import SAFE_INTERIORS, ocr_regions, regions
from tests.unit.cases.test_cms1500_template_first import OCR, template
from workers.standard_form_extraction.extractor import StandardFormExtractionService


def test_expansion_stays_in_public_label_free_interiors_and_preserves_original():
    t=template();original=regions(t);expanded=ocr_regions(t)
    for name,parts in expanded.items():
        for i,p in enumerate(parts):
            c=original[name][i]
            assert p.x0<=c.x0<c.x1<=p.x1 and p.y0<=c.y0<c.y1<=p.y1
            if name in SAFE_INTERIORS:
                b=SAFE_INTERIORS[name][i];w=1712;h=2214
                assert p.x0>=round(b[0]*w) and p.x1<=round(b[2]*w)
                assert p.y0>=round(b[1]*h) and p.y1<=round(b[3]*h)
    assert expanded["principal_diagnosis"]==original["principal_diagnosis"]


def test_multiline_addresses_use_region_mode_and_canonical_evidence_is_preserved():
    t=template();expanded=ocr_regions(t);calls=[]
    class Modes(OCR):
        def extract_line(self,image,*box):calls.append(("line",box));return super().extract_region(image,*box)
        def extract_region(self,image,*box):calls.append(("region",box));return super().extract_region(image,*box)
    fields=StandardFormExtractionService(Modes({})).extract_cms1500_fields(
        Image.new("RGB",(1712,2214)),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    for name in ("patient_address","insured_address","provider_name"):
        for p in expanded[name]:assert ("region",(p.x0,p.y0,p.x1,p.y1)) in calls
    p=regions(t)["patient_name"][0];assert ("line",(p.x0,p.y0,p.x1,p.y1)) in calls
    evidence=fields[0].candidates[0];provenance=evidence.provenance
    assert provenance.canonical_bbox.x0==regions(t)["patient_name"][0].x0
    assert provenance.ocr_crop_bbox.x0==expanded["patient_name"][0].x0
    before=provenance.model_dump()
    evidence.bounding_box=evidence.bounding_box.model_copy(update={"x0":1})
    assert provenance.model_dump()==before


@pytest.mark.parametrize("values,expected,ambiguous",[
    (["1234567890"],"",False),(["1234567893"],"1234567893",False),
    (["1234567890","1234567893"],"1234567893",False),
    (["1234567893","1234567893"],"1234567893",False),
    (["1234567893","1245319599"],"",True)])
def test_rendering_npi_valid_rows_only(values,expected,ambiguous):
    t=template();parts=ocr_regions(t)["provider_npi"]
    engine=OCR({(p.x0,p.y0,p.x1,p.y1):v for p,v in zip(parts,values)})
    fields=StandardFormExtractionService(engine).extract_cms1500_fields(
        Image.new("RGB",(1712,2214)),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    f=next(f for f in fields if f.field_name=="provider_npi")
    assert f.raw_value==expected and len({e.provenance.localization_region_id for e in f.candidates})==6
    assert ("AMBIGUOUS_MULTIROW" in f.validation_reasons)==ambiguous


def test_missing_field_reports_first_outcome_without_creating_blank_field():
    fields=[]
    assert canonical_field_outcomes({"patient_name"},fields,registered=False,region_names=set(),persisted_ids=set())=={"patient_name":"REGISTRATION_UNAVAILABLE"}
    assert canonical_field_outcomes({"patient_name"},fields,registered=True,region_names=set(),persisted_ids=set())=={"patient_name":"NO_CANONICAL_REGION"}
    assert canonical_field_outcomes({"patient_name"},fields,registered=True,region_names={"patient_name"},persisted_ids=set())=={"patient_name":"FIELD_ASSEMBLY_DROPPED"}
    assert fields==[]


def test_valid_canonical_identifier_cannot_be_replaced_by_padding_variant():
    t=template();c=regions(t)["federal_tax_no"][0];e=ocr_regions(t)["federal_tax_no"][0]
    engine=OCR({(c.x0,c.y0,c.x1,c.y1):"123456789",(e.x0,e.y0,e.x1,e.y1):"987654321"})
    fields=StandardFormExtractionService(engine).extract_cms1500_fields(
        Image.new("RGB",(1712,2214)),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    field=next(f for f in fields if f.field_name=="federal_tax_no")
    assert field.raw_value=="123456789"
    assert (e.x0,e.y0,e.x1,e.y1) not in engine.calls
    assert field.candidates[0].provenance.preprocessing_version=="CANONICAL_PRIMARY"


def test_invalid_canonical_identifier_recovers_with_bounded_crop_and_keeps_both():
    t=template();c=regions(t)["federal_tax_no"][0];e=ocr_regions(t)["federal_tax_no"][0]
    engine=OCR({(c.x0,c.y0,c.x1,c.y1):"123",(e.x0,e.y0,e.x1,e.y1):"123456789"})
    fields=StandardFormExtractionService(engine).extract_cms1500_fields(
        Image.new("RGB",(1712,2214)),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    field=next(f for f in fields if f.field_name=="federal_tax_no")
    assert field.raw_value=="123456789" and len(field.candidates)==2
    assert {e.provenance.preprocessing_version for e in field.candidates}=={"CANONICAL_PRIMARY","BOUNDED_VALUE_RECOVERY"}
