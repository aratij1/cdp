from pathlib import Path


def test_taxonomy_package_has_no_model_or_extractor_dispatch_authority():
    text = "\n".join(path.read_text("utf-8") for path in Path("packages/document_taxonomy").glob("*.py"))
    assert "LightGBM" not in text and "XGBoost" not in text and "Gemini" not in text
    assert "RouteDecision(" not in text


def test_rejected_components_are_fail_closed():
    import json
    lifecycle = json.loads(Path("config/router_lifecycle.json").read_text("utf-8"))
    for component in ("ROUTER_V4", "ML_ELIGIBILITY_V1", "VISUAL_ROUTER_V1", "VISUAL_CONTRADICTION_V1"):
        assert lifecycle[component]["runtime"] == "DISABLED"
