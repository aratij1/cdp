from pathlib import Path
def test_ml_layer_has_no_finalization_or_dispatch_authority():
    text="\n".join(p.read_text("utf-8") for p in Path("packages/document_routing/ml").glob("*.py"))
    assert "RouteDecision(" not in text
    assert "extractor_dispatch" not in text
    assert "claim_processing" not in text
    assert "MLRouteEvidence" in text
