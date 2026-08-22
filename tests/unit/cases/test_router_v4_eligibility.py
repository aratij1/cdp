from packages.document_routing import MultiSignalRouter,evaluate_standard_eligibility
from PIL import Image,ImageDraw
from workers.page_detection.text_extraction import TextLine

def _decision(lines,grid=True):
    image=Image.new("L",(850,1100),255);d=ImageDraw.Draw(image)
    if grid:
      for y in range(70,1030,65):d.line((30,y,820,y),fill=0,width=2)
      for x in range(30,821,100):d.line((x,70,x,1030),fill=0,width=2)
    return MultiSignalRouter.load().route(image,lines)

def test_identity_alone_does_not_create_eligibility():
    d=_decision([TextLine("CMS 1500",10,10,120,30,1)],grid=False)
    assert evaluate_standard_eligibility(d,"CMS1500",stage=2).eligible is False

def test_eligibility_is_inspectable_and_has_gap_evidence():
    d=_decision([TextLine("TYPE OF BILL",600,50,760,80,1),TextLine("STATEMENT COVERS",500,100,760,130,1),TextLine("REVENUE CODE",50,300,200,330,1),TextLine("HCPCS",250,300,330,330,1)])
    value=evaluate_standard_eligibility(d,"UB04",stage=4)
    assert value.path_details
    condition=value.path_details["institutional"]["conditions"]["structure"]
    assert set(condition)>={"observed_value","required_value","absolute_gap","relative_gap"}

def test_default_rem03a_flag_is_disabled():
    from packages.document_routing import InvariantRouterV4
    config=InvariantRouterV4.load().config["experiments"]
    assert config["enable_rem03a_eligibility"] is False

def test_disabled_rem03a_does_not_change_default_decision_contract_values():
    from packages.document_routing import InvariantRouterV4
    decision=InvariantRouterV4.load().route(Image.new("L",(850,1100),255),[])
    assert decision.family_eligibility=={}
