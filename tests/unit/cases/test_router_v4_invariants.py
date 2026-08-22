from dataclasses import dataclass

from PIL import Image, ImageDraw

from packages.document_routing import InvariantRouterV4, MultiSignalRoute, describe_structure


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


def _grid(rows=10, columns=5):
    image=Image.new("L",(850,1100),"white"); draw=ImageDraw.Draw(image)
    for y in range(80,1000,900//rows): draw.line((45,y,805,y),fill=0,width=2)
    for x in range(45,806,760//columns): draw.line((x,80,x,1000),fill=0,width=2)
    return image


def _lines(*items):
    return [Line(value,70+(i%2)*400,80+i*100,350+(i%2)*400,120+i*100) for i,value in enumerate(items)]


def test_descriptors_are_resolution_independent_and_bounded():
    image=_grid()
    first=describe_structure(image); second=describe_structure(image.resize((1700,2200)))
    assert len(first.grid_density_map)==12
    assert all(0 <= x <= 1 for x in first.region_occupancy)
    assert abs(first.service_table_repetition-second.service_table_repetition) <= .1


def test_v4_routes_ub_from_structure_and_corroborating_anchors_without_title():
    result=InvariantRouterV4.load().route(_grid(14,7),_lines(
        "TYPE OF BILL","STATEMENT COVERS","REVENUE CODE","HCPCS","TOTAL CHARGES"))
    assert result.route is MultiSignalRoute.UB04
    assert "ROUTER_V4_INVARIANT_STANDARD" in result.reason_codes


def test_healthcare_vocabulary_alone_cannot_false_route_standard():
    result=InvariantRouterV4.load().route(Image.new("L",(850,1100),"white"),_lines(
        "PATIENT","NPI","DIAGNOSIS","HCPCS","CHARGES","PROVIDER","SERVICE DATE"))
    assert result.route not in {MultiSignalRoute.CMS1500,MultiSignalRoute.UB04}


def test_attachment_golden_path_remains_safe_unstructured_fallback():
    result=InvariantRouterV4.load().route(Image.new("L",(850,1100),"white"),_lines(
        "See attached clinical narrative regarding treatment."))
    assert result.route is MultiSignalRoute.UNKNOWN_UNSTRUCTURED
    assert result.reason_codes==["ROUTER_V4_SAFE_UNSTRUCTURED_FALLBACK"]


def test_nonclaim_requires_negative_and_low_claim_evidence():
    router=InvariantRouterV4.load(); blank=Image.new("L",(850,1100),"white")
    assert router.route(blank,_lines("COVER SHEET","MEMORANDUM")).route is MultiSignalRoute.NON_CLAIM
    assert router.route(blank,_lines("COVER SHEET","PATIENT","DIAGNOSIS","PROVIDER")).route is not MultiSignalRoute.NON_CLAIM

