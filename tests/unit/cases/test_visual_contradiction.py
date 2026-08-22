from packages.document_routing.router import MultiSignalRoute, RoutingEvidence
from packages.document_routing.visual.contracts import VisualRouteEvidence
from packages.document_routing.visual.contradiction import VisualContradictionService


def _visual(family: str):
    probabilities = {"CMS1500": .03, "UB04": .03, "UNKNOWN_STRUCTURED": .02,
                     "UNKNOWN_UNSTRUCTURED": .01, "NON_CLAIM": .01}
    probabilities[family] = .90
    return [VisualRouteEvidence(family=name, probability=value, model_version="frozen-v1", feature_version="hog-v1")
            for name, value in probabilities.items()]


def _det(structure, anchors=None, geometry=None):
    return RoutingEvidence(route=MultiSignalRoute.UNKNOWN_STRUCTURED, confidence=.5, scores={},
        best_score=.5, second_best_score=.4, margin=.1, grid_score=.5,
        horizontal_line_score=.5, vertical_line_score=.5, healthcare_label_density=.5,
        matched_anchors={}, reason_codes=[], standard_structure=structure,
        weighted_anchor_coverage=anchors or {}, anchor_geometry_score=geometry or {})


def test_ub_requires_two_independent_contradictions():
    one = _det({"UB04": .60, "CMS1500": .40, "service_table_score": .30})
    assert not VisualContradictionService(2).evaluate(_visual("UB04"), one).contradiction_detected
    two = _det({"UB04": .60, "CMS1500": .40, "service_table_score": .10})
    result = VisualContradictionService(2).evaluate(_visual("UB04"), two)
    assert result.contradiction_detected
    assert {"STRUCTURAL_CONTRADICTION", "SERVICE_TABLE_CONTRADICTION"} <= set(result.contradiction_classes)


def test_missing_weak_signal_does_not_veto_cms():
    result = VisualContradictionService(4).evaluate(_visual("CMS1500"), _det({"CMS1500": .75, "UB04": .20}))
    assert not result.contradiction_detected
    assert result.recommended_action == "VISUAL_STANDARD_NOT_CONTRADICTED"


def test_opposing_evidence_is_symmetric_for_standard_families():
    cms = VisualContradictionService(4).evaluate(_visual("CMS1500"), _det(
        {"CMS1500": .30, "UB04": .90, "service_table_score": .30}, {"UB04": .5}, {"UB04": .5}))
    ub = VisualContradictionService(4).evaluate(_visual("UB04"), _det(
        {"UB04": .30, "CMS1500": .90, "service_table_score": .25}, {"CMS1500": .5}, {"CMS1500": .5}))
    assert cms.contradiction_detected and ub.contradiction_detected
    assert "OPPOSING_STANDARD_EVIDENCE" in cms.contradiction_classes
    assert "OPPOSING_STANDARD_EVIDENCE" in ub.contradiction_classes
