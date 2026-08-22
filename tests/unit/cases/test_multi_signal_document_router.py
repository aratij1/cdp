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


def test_explicit_ub_identity_and_specific_anchor_use_identity_backed_gate():
    decision=MultiSignalRouter.load().route(_image(),_lines(
        "UB-04", "TYPE OF BILL", "CLAIM",
    ))
    assert decision.route is MultiSignalRoute.UB04
    assert decision.eligibility["UB04"]
    assert "UB04_IDENTITY_CONFIRMED" in decision.reason_codes


def test_identity_without_family_specific_anchor_stays_fail_closed():
    decision=MultiSignalRouter.load().route(_image(False),_lines("UB-04", "CLAIM"))
    assert decision.route is not MultiSignalRoute.UB04


def test_ocr_safe_normalization_is_bounded_to_multi_token_labels():
    decision=MultiSignalRouter.load().route(_image(),_lines(
        "UB-04", "TYPE  OF   BIIL", "PATLENT CONTROL", "PRINCIPAL DIAGNOS1S",
    ))
    assert decision.route is MultiSignalRoute.UB04
    assert decision.normalized_anchor_count >= 2
    generic=MultiSignalRouter.load().route(_image(),_lines("UN1TS", "NAME", "DATE"))
    assert generic.route not in {MultiSignalRoute.CMS1500,MultiSignalRoute.UB04}


def test_structure_confirmed_path_does_not_require_identity():
    lines=[
        TextLine("TYPE OF BILL",760,70,960,100,.95),
        TextLine("PATIENT CONTROL",600,80,790,110,.95),
        TextLine("STATEMENT COVERS",650,150,900,180,.95),
        TextLine("REVENUE CODE",40,420,220,450,.95),
        TextLine("HCPCS",300,430,390,460,.95),
        TextLine("UNITS",650,440,720,470,.95),
        TextLine("TOTAL CHARGES",760,450,950,480,.95),
        TextLine("PRINCIPAL DIAGNOSIS",50,900,300,930,.95),
    ]
    decision=MultiSignalRouter.load().route(_image(),lines)
    assert not decision.matched_anchors["UB04_IDENTITY"]
    assert decision.eligibility["UB04"]
    assert decision.route is MultiSignalRoute.UB04
    assert "UB04_STRUCTURE_CONFIRMED" in decision.reason_codes
