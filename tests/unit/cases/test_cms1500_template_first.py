"""Public-form geometry and synthetic extraction; no engineering labels."""
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from packages.document_routing.router import _phrase_match
from packages.domain.enums import ClaimFormType
from packages.templates.cms1500_boxes import BOXES, value_template
from packages.templates.cms1500_boxes import ocr_regions as regions
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
    ("federal_tax_no","25"),("total_charge","28"),("provider_name","31")])
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


def test_service_rows_use_public_value_cells_and_same_24j_region():
    from packages.templates.cms1500_boxes import service_regions
    from packages.templates.models import ServiceLineTableRegion
    t=template()
    t.service_line_region=ServiceLineTableRegion(table_x0=0,table_x1=1712,
        table_y0=1400,table_y1=1750,max_rows=6,row_height_px=55,columns=[])
    from packages.templates.cms1500_boxes import regions as canonical_regions
    header=canonical_regions(t)["provider_npi"]
    first=service_regions(t,0)
    for i in range(6):
        npi=next(r for r in service_regions(t,i) if r.field_name=="rendering_provider_npi")
        assert (npi.x0,npi.y0,npi.x1,npi.y1)==(header[i].x0,header[i].y0,header[i].x1,header[i].y1)
    date=first[0];npi=first[-1]
    ocr=OCR({(date.x0,date.y0,date.x1,date.y1):"01/01/2025",
        (npi.x0,npi.y0,npi.x1,npi.y1):"1234567893"})
    lines=StandardFormExtractionService(ocr).extract_service_lines(
        Image.new("L",(1712,2214),255),t,1,canonical_cms=True)
    assert len(lines)==1
    assert lines[0].fields[0].raw_value=="01/01/2025"
    assert lines[0].fields[0].candidates[0].provenance.crop_sha256
    assert (date.x0,date.y0,date.x1,date.y1) in ocr.calls


def test_diagnosis_a_includes_value_above_baseline_and_stops_before_b():
    box=BOXES["principal_diagnosis"][2][0]
    # Public form: Box 21 heading ends above .58; first value baseline is .595;
    # column B begins at .23 and the E row begins below .605.
    assert .580 < box[1] < .587
    assert .595 < box[3] < .605
    assert box[2] < .23


def test_verified_line_ocr_preserves_engine_score_floor_and_source_coordinates():
    from workers.page_detection.text_extraction import RapidOCRTextExtractor
    class Backend:
        text_score=.5
        def __call__(self,array,**kwargs):
            assert array.shape[:2]==(20,80)
            assert kwargs=={"use_det":False,"use_cls":False}
            return [["SYNTHETIC",.95],["LOW",.49]], [0.01]
    lines=RapidOCRTextExtractor(backend=Backend()).extract_line(Image.new("RGB",(200,200)),10,30,90,50)
    assert len(lines)==1 and lines[0].text=="SYNTHETIC"
    assert (lines[0].x0,lines[0].y0,lines[0].x1,lines[0].y1)==(10,30,90,50)


def test_line_and_detector_ocr_never_share_cache_entries():
    from workers.cascade.instrumented_text_extractor import CachedInstrumentedTextExtractor
    class Backend(OCR):
        def extract_line(self,image,x0,y0,x1,y1):
            self.calls.append("line")
            return [TextLine("LINE",x0,y0,x1,y1,.95)]
    backend=Backend({(0,0,80,20):"DETECTOR"});cached=CachedInstrumentedTextExtractor(backend)
    im=Image.new("RGB",(200,200))
    assert cached.extract_region(im,10,30,90,50)[0].text=="DETECTOR"
    assert cached.extract_line(im,10,30,90,50)[0].text=="LINE"
    assert cached.extract_line(im,10,30,90,50)[0].x0==10
    assert len(backend.calls)==2


def test_provider_name_uses_physician_signature_not_billing_organization():
    assert BOXES["provider_name"][0]=="31"
    assert BOXES["provider_name"][2][0][2]<.315
    assert BOXES["provider_npi"][0]=="24J"


def test_box31_includes_left_signature_entry_and_uses_multiline_detection():
    t = template()
    region = regions(t)["provider_name"][0]
    # Public Box 31 begins at the same form margin as the other left-column cells.
    assert region.x0 <= regions(t)["patient_name"][0].x0
    class MixedOCR(OCR):
        def extract_line(self, image, x0, y0, x1, y1):
            assert (x0, y0, x1, y1) != (region.x0, region.y0, region.x1, region.y1)
            return self.extract_region(image, x0, y0, x1, y1)
    engine = MixedOCR({(region.x0, region.y0, region.x1, region.y1): "SYNTHETIC PHYSICIAN MD"})
    fields = StandardFormExtractionService(engine).extract_cms1500_fields(
        Image.new("L", (1712, 2214), 255), t, 1, SimpleNamespace(authorizes_fixed_roi=True))
    field = next(f for f in fields if f.field_name == "provider_name")
    assert field.raw_value == "SYNTHETIC PHYSICIAN MD"
    assert field.candidates[0].provenance.preprocessing_profile == "VERIFIED_MULTILINE_VALUE"
