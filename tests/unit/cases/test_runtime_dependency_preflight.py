import pytest
from PIL import Image

from scripts.runtime_dependency_preflight import run
from workers.unstructured_extraction.layoutlmv3_adapter import (
    LayoutLMv3Adapter,
    ModelNotAvailableError,
)


def test_standard_route_needs_no_layout_checkpoint(monkeypatch):
    monkeypatch.setattr("scripts.runtime_dependency_preflight.importlib.util.find_spec", lambda _: object())
    plan = {"pages": [{"identity_verified": True, "registration_accepted": True,
                       "canonical_entered": True, "fallback_requested": False}]}
    result = run("candidate", route_plan=plan)
    assert result["status"] == "PASS"
    assert result["dependencies"][1]["status"] == "NOT_REQUIRED_FOR_CMS_STANDARD_ROUTE"


def test_fallback_is_not_implemented_even_with_checkpoint(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{}")
    monkeypatch.setenv("CDP_LAYOUTLMV3_CHECKPOINT", str(tmp_path))
    result = run(route_plan={"pages": [{"fallback_requested": True}]})
    assert result["status"] == "FAIL"
    assert result["dependencies"][1]["status"] == "FALLBACK_RUNTIME_NOT_IMPLEMENTED"
    with pytest.raises(ModelNotAvailableError, match="FALLBACK_RUNTIME_NOT_IMPLEMENTED"):
        LayoutLMv3Adapter(str(tmp_path)).extract(Image.new("L", (10, 10)), [])


def test_missing_route_evidence_does_not_claim_standard_only():
    assert run()["dependencies"][1]["status"] == "ROUTE_PLAN_REQUIRED"
