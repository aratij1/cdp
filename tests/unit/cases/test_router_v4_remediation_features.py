from dataclasses import dataclass
from PIL import Image,ImageDraw
from packages.document_routing import build_router_feature_bundle,detect_content_bounds,recover_token_groups
from packages.document_routing import InvariantRouterV4
from packages.document_routing.features import NormalizedLine

@dataclass
class Line:
    text:str;x0:float;y0:float;x1:float;y1:float

def test_content_bounds_ignore_scanner_padding():
    image=Image.new("L",(1000,1400),255);ImageDraw.Draw(image).rectangle((120,180,880,1220),outline=0,width=4)
    value=detect_content_bounds(image)
    assert 100<=value.content_x0<=130 and 870<=value.content_x1<=900
    assert value.effective_width < image.width

def test_controlled_token_group_recovers_multiline_corruption():
    lines=(NormalizedLine("PRINCIPAL",.1,.1,.3,.13),NormalizedLine("DIAGN0",.1,.14,.2,.17),NormalizedLine("SIS",.2,.14,.26,.17))
    enriched,matches=recover_token_groups(lines)
    assert any(x.anchor_id=="principal diagnosis" for x in matches)
    assert any(x.text=="principal diagnosis" for x in enriched)

def test_generic_diagnosis_alone_is_not_discriminative_anchor():
    _,matches=recover_token_groups((NormalizedLine("DIAGNOSIS",.1,.1,.3,.13),))
    assert not any(x.anchor_id=="principal diagnosis" for x in matches)

def test_feature_bundle_uses_one_content_relative_geometry():
    image=Image.new("L",(1000,1400),255);ImageDraw.Draw(image).rectangle((100,150,900,1250),outline=0,width=3)
    bundle=build_router_feature_bundle(image,[Line("TYPE",120,180,180,210),Line("OF BILL",190,180,290,210)])
    assert bundle.content_image.width < image.width
    assert bundle.geometry.effective_width==bundle.content_image.width
    assert bundle.token_group_matches

def test_remediation_features_are_disabled_in_default_v4():
    router=InvariantRouterV4.load()
    assert router.config["experiments"]["rem01_content_geometry"] is False
    assert router.config["experiments"]["rem02_token_groups"] is False
