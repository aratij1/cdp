"""Public-form geometry and synthetic extraction; no engineering labels."""
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from packages.document_routing.router import _phrase_match
from packages.domain.enums import ClaimFormType
from packages.templates.cms1500_boxes import BOXES, regions, value_template
from packages.templates.models import ReferenceDimensions, Template
from workers.document_preparation.preprocessing import detect_orientation
from workers.page_detection.text_extraction import TextLine
from workers.standard_form_extraction.extractor import StandardFormExtractionService


def template():
    return value_template(Template(template_id="cms1500",version="02-12",form_type=ClaimFormType.CMS1500,
        reference_dimensions=ReferenceDimensions(width_px=1712,height_px=2214),
        field_regions=[],anchor_definitions=[]))


@pytest.mark.parametrize("field,box",[("patient_name","2"),("patient_dob","3"),
    ("insured_address","7"),("principal_diagnosis","21A"),("provider_npi","24J"),
    ("federal_tax_no","25"),("total_charge","28")])
def test_canonical_box_identity_and_normalization(field,box):
    assert BOXES[field][0]==box
    assert all(0<=x0<x1<=1 and 0<=y0<y1<=1 for x0,y0,x1,y1 in BOXES[field][2])


def test_patient_and_insured_boxes_never_overlap():
    assert BOXES["patient_name"][2][0][2]<BOXES["insured_name"][2][0][0]
    assert all(p[2]<i[0] for p in BOXES["patient_address"][2] for i in BOXES["insured_address"][2])
    assert BOXES["federal_tax_no"][2][0][2]<BOXES["provider_npi"][2][0][0]
    assert BOXES["total_charge"][2][0][1]>BOXES["provider_npi"][2][-1][3]


class OCR:
    engine_name="rapidocr"
    model_name="synthetic"
    model_version="1"
    def __init__(self,values):self.values=values;self.calls=[]
    def extract(self,image):raise AssertionError("FULL_PAGE_FIELD_OCR_FORBIDDEN")
    def extract_region(self,image,x0,y0,x1,y1):
        self.calls.append((x0,y0,x1,y1))
        value=self.values.get((x0,y0,x1,y1),"")
        return [TextLine(value,x0,y0,x1,y1,.95)] if value else []


def test_fields_use_only_named_value_boxes_and_keep_raw_value_and_provenance():
    t=template();r=regions(t)
    def b(field,i=0):
        p=r[field][i];return p.x0,p.y0,p.x1,p.y1
    ocr=OCR({b("patient_name"):"SYNTHETIC PATIENT",b("insured_name"):"SYNTHETIC INSURED",
        b("federal_tax_no"):"012345678",b("total_charge"):"$12.34",
        b("principal_diagnosis"):"A12.3",b("provider_npi"):"1234567893"})
    fields=StandardFormExtractionService(ocr).extract_cms1500_fields(
        Image.new("L",(1712,2214),255),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    byname={f.field_name:f for f in fields}
    assert byname["patient_name"].raw_value=="SYNTHETIC PATIENT"
    assert byname["federal_tax_no"].raw_value=="012345678"
    assert byname["total_charge"].raw_value=="$12.34"
    assert byname["total_charge"].normalized_value=="12.34"
    assert byname["principal_diagnosis"].raw_value=="A12.3"
    assert byname["patient_name"].candidates[0].tokens
    assert byname["patient_name"].candidates[0].provenance.crop_sha256
    assert len(ocr.calls)==sum(len(parts) for parts in r.values())
    address=byname["insured_address"]
    assert address.candidates[0].raw_text==address.raw_value
    assert len(address.candidates[0].provenance.upstream_candidate_ids)==3


def test_rendering_rows_disagree_without_selecting_a_billing_or_first_row_npi():
    t=template();parts=regions(t)["provider_npi"]
    values={(p.x0,p.y0,p.x1,p.y1):v for p,v in zip(parts,["1234567893","1245319599"])}
    fields=StandardFormExtractionService(OCR(values)).extract_cms1500_fields(
        Image.new("L",(1712,2214),255),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    f=next(f for f in fields if f.field_name=="provider_npi")
    assert not f.raw_value
    assert "RENDERING_PROVIDER_ROW_AMBIGUITY" in f.validation_reasons
    assert len(f.candidates)==6


def test_unverified_geometry_never_calls_ocr():
    with pytest.raises(ValueError,match="VERIFIED_REGISTERED"):
        StandardFormExtractionService(OCR({})).extract_cms1500_fields(
            Image.new("L",(1712,2214),255),template(),1,SimpleNamespace(authorizes_fixed_roi=False))


@pytest.mark.parametrize("anchor,printed",[("patients name","PATIENT'S NAME"),
    ("insured id number","INSURED"+chr(8217)+"S I.D. NUMBER"),("federal tax id","FEDERAL TAX I.D.")])
def test_printed_label_variants_match_without_lowering_similarity(anchor,printed):
    assert _phrase_match(anchor,printed)[0] in {"EXACT","NORMALIZED"}


def test_projection_ties_cannot_invent_an_upside_down_orientation():
    rng=np.random.default_rng(41)
    for _ in range(20):
        pixels=rng.integers(0,255,size=(103,79),dtype=np.uint8)
        assert detect_orientation(Image.fromarray(pixels)) in {0,90}


def test_canonical_crop_tokens_survive_persistence_and_decision_adapter():
    from packages.domain.extraction import ExtractedField
    from packages.evidence_decision.adapters import ocr_candidates_from_field
    t=template();p=regions(t)["patient_name"][0]
    fields=StandardFormExtractionService(OCR({(p.x0,p.y0,p.x1,p.y1):"SYNTHETIC PATIENT"})).extract_cms1500_fields(
        Image.new("L",(1712,2214),255),t,1,SimpleNamespace(authorizes_fixed_roi=True))
    field=ExtractedField.model_validate_json(fields[0].model_dump_json())
    candidates=ocr_candidates_from_field(field)
    assert candidates[0].tokens[0].text=="SYNTHETIC PATIENT"
    assert candidates[0].tokens[0].bounding_box.x0==p.x0
    assert candidates[0].tokens[0].bounding_box.image_width==1712


def test_tesseract_tsv_literal_quote_cannot_swallow_subsequent_words():
    from workers.cascade.tesseract_adapter import parse_tsv
    header="level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    payload=header+'5\t1\t1\t1\t1\t1\t10\t20\t5\t10\t90\t"\n'
    payload+='5\t1\t1\t1\t1\t2\t30\t20\t50\t10\t95\tINSURED\n'
    payload+='5\t1\t1\t1\t1\t3\t90\t20\t25\t10\t92\tI.D.NUMBER\n'
    words=parse_tsv(payload)
    assert len(words)==3
    assert words[0].text=='"'
    assert words[1].text=='INSURED'
    assert words[2].x0==90
    assert _phrase_match("insured id number"," ".join(w.text for w in words))[0]=="NORMALIZED"


def test_crop_ocr_uses_bounded_threads_and_reuses_loaded_engine(monkeypatch):
    import sys

    from workers.page_detection.text_extraction import RapidOCRTextExtractor
    calls=[]
    def factory(**kwargs):
        calls.append(kwargs)
        return object()
    monkeypatch.setitem(sys.modules,"rapidocr_onnxruntime",SimpleNamespace(RapidOCR=factory))
    extractor=RapidOCRTextExtractor()
    assert extractor._load() is extractor._load()
    assert calls==[{"intra_op_num_threads":2,"inter_op_num_threads":1}]
