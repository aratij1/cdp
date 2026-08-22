from PIL import Image

from packages.document_routing import MultiSignalRouter, build_router_observation
from workers.page_detection.text_extraction import TextLine


def test_observation_persists_aggregates_without_ocr_text():
    image=Image.new("L",(1000,1300),255)
    lines=[TextLine("PATIENT MEMBER CLAIM",10,10,300,30,.9)]
    decision=MultiSignalRouter.load().route(image,lines)
    value=build_router_observation(document_id="opaque-1",image=image,lines=lines,decision=decision)
    payload=value.model_dump_json()
    assert value.ocr_token_count==3
    assert value.healthcare_token_count==3
    assert "PATIENT" not in payload
    assert value.document_id=="opaque-1"
