from PIL import Image, ImageDraw

from packages.document_routing import MultiSignalRoute, MultiSignalRouter
from packages.ub04 import build_ub04_fingerprint
from workers.page_detection.text_extraction import TextLine


def _image(grid=True):
    image=Image.new("L",(1000,1300),255)
    if grid:
        draw=ImageDraw.Draw(image)
        for y in range(150,1100,100): draw.line((40,y,960,y),fill=0,width=2)
        for x in (40,250,500,750,960): draw.line((x,150,x,1100),fill=0,width=2)
    return image


def _lines(*values):
    return [TextLine(value,10,index*30,500,index*30+20,.95) for index,value in enumerate(values)]


def test_ub_fingerprint_requires_multiple_independent_signals():
    decision=MultiSignalRouter.load().route(_image(),_lines(
        "UB-04", "TYPE OF BILL", "PATIENT CONTROL", "STATEMENT COVERS",
        "PRINCIPAL DIAGNOSIS", "REVENUE CODE HCPCS SERVICE DATE UNITS TOTAL CHARGES",
    ))
    assert decision.route is MultiSignalRoute.UB04
    evidence=build_ub04_fingerprint(decision,width=1000,height=1300)
    assert evidence.identity_anchor_present
    assert evidence.service_line_anchor_count >= 4
    assert evidence.type_of_bill_evidence


def test_healthcare_vocabulary_without_standard_identity_routes_custom():
    decision=MultiSignalRouter.load().route(_image(),_lines(
        "PATIENT MEMBER PROVIDER", "DIAGNOSIS PROCEDURE SERVICE DATE", "NPI CHARGE CLAIM",
    ))
    assert decision.route is MultiSignalRoute.UNKNOWN_STRUCTURED


def test_multiple_negative_anchors_and_low_healthcare_density_stop_nonclaim():
    decision=MultiSignalRouter.load().route(_image(False),_lines(
        "DOCUMENT COVER SHEET", "CORRESPONDENCE MEMORANDUM",
    ))
    assert decision.route is MultiSignalRoute.NON_CLAIM


def test_close_standard_scores_fail_closed_to_unknown():
    decision=MultiSignalRouter.load().route(_image(),_lines(
        "CMS 1500 UB 04", "PATIENT CONTROL", "HEALTH INSURANCE CLAIM FORM",
    ))
    assert decision.route not in {MultiSignalRoute.CMS1500,MultiSignalRoute.UB04}
