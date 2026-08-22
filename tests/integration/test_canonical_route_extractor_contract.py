import pytest

from packages.document_routing import MultiSignalRoute
from packages.extraction_routing import ExtractionTarget, extraction_target


@pytest.mark.parametrize(("route","target"),[
    (MultiSignalRoute.CMS1500,ExtractionTarget.CMS1500_STANDARD),
    (MultiSignalRoute.UB04,ExtractionTarget.UB04_STANDARD),
    (MultiSignalRoute.UNKNOWN_STRUCTURED,ExtractionTarget.UNKNOWN_STRUCTURED_LAYOUT),
    (MultiSignalRoute.UNKNOWN_UNSTRUCTURED,ExtractionTarget.UNKNOWN_UNSTRUCTURED_LAYOUT),
    (MultiSignalRoute.NON_CLAIM,ExtractionTarget.STOP_NON_CLAIM),
])
def test_router_route_is_losslessly_consumed_by_extractor_dispatch(route,target):
    assert extraction_target(route) is target


def test_unknown_structured_never_collapses_to_unstructured_target():
    assert extraction_target("UNKNOWN_STRUCTURED") is not extraction_target("UNKNOWN_UNSTRUCTURED")


def test_nonclaim_stops_before_extraction():
    assert extraction_target("NON_CLAIM") is ExtractionTarget.STOP_NON_CLAIM
