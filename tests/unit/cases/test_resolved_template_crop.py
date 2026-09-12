"""Resolved ROI must govern both pixels read and emitted geometry."""
from PIL import Image

from packages.domain.enums import ClaimFormType
from packages.templates.models import FieldRegion, ReferenceDimensions, Template
from workers.page_detection.text_extraction import TextLine
from workers.standard_form_extraction.extractor import StandardFormExtractionService


def test_single_resolved_box_is_used_instead_of_template_pixels():
    class OCR:
        engine_name = "rapidocr"
        def __init__(self): self.calls = []
        def extract_region(self,image,x0,y0,x1,y1):
            self.calls.append((x0,y0,x1,y1))
            return [TextLine("SYNTHETIC",0,0,20,10,0.9)]
    ocr=OCR()
    template=Template(template_id="synthetic",version="1",form_type=ClaimFormType.CMS1500,
        reference_dimensions=ReferenceDimensions(width_px=100,height_px=100),anchor_definitions=[],
        field_regions=[FieldRegion(field_name="patient_name",x0=10,y0=10,x1=30,y1=20)])
    image=Image.new("RGB",(200,200),"white")
    fields=StandardFormExtractionService(ocr).extract_fields(image,template,1,
        {"patient_name":((80,90,130,110),)})
    assert ocr.calls==[(76,86,134,114)]
    assert (fields[0].bounding_box.x0,fields[0].bounding_box.y0,
            fields[0].bounding_box.x1,fields[0].bounding_box.y1)==(80,90,130,110)
    assert fields[0].bounding_box.image_width==200
    assert fields[0].raw_value=="SYNTHETIC"
