import pytest

from packages.extraction_routing import ExtractionTarget, extraction_target
from packages.processing_routes.contracts import ProcessingRoute


@pytest.mark.parametrize(("route","target"),[
    (ProcessingRoute.CMS_STANDARD_EXTRACTOR,ExtractionTarget.CMS1500_STANDARD),
    (ProcessingRoute.UB_STANDARD_EXTRACTOR,ExtractionTarget.UB04_STANDARD),
    (ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR,ExtractionTarget.UNKNOWN_STRUCTURED_LAYOUT),
    (ProcessingRoute.UNSTRUCTURED_EXTRACTOR,ExtractionTarget.UNKNOWN_UNSTRUCTURED_LAYOUT),
    (ProcessingRoute.STOP_NON_CLAIM,ExtractionTarget.STOP_NON_CLAIM),
])
def test_router_route_is_losslessly_consumed_by_extractor_dispatch(route,target):
    assert extraction_target(route) is target


def test_unknown_structured_never_collapses_to_unstructured_target():
    assert extraction_target("LAYOUT_STRUCTURED_EXTRACTOR") is not extraction_target("UNSTRUCTURED_EXTRACTOR")


def test_nonclaim_stops_before_extraction():
    assert extraction_target("STOP_NON_CLAIM") is ExtractionTarget.STOP_NON_CLAIM


def test_classifier_nomination_cannot_dispatch_fixed_extractor():
    with pytest.raises(ValueError):
        extraction_target("CMS1500")
