from pathlib import Path
def test_visual_layer_has_evidence_only_authority():
    text="\n".join(p.read_text("utf-8") for p in Path("packages/document_routing/visual").glob("*.py"))
    assert "RouteDecision(" not in text and "extractor" not in text and "VisualRouteEvidence" in text
