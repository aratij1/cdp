from packages.domain.common import BoundingBox
from packages.ocr.contracts import OCRCandidate
from packages.route_registry import RouteDefinition, RouteLifecycle, RouteRegistry
from packages.shadow_evaluation import InMemoryShadowObservationSink, ShadowEvaluationService


BOX = BoundingBox(x0=0, y0=0, x1=1, y1=1, image_width=1, image_height=1)


def candidate(value: str, engine: str) -> OCRCandidate:
    return OCRCandidate(
        value=value, raw_value=value, engine=engine, model_name=engine,
        model_version="1", preprocessing_variant="test", raw_confidence=.9,
        calibrated_confidence=None, bounding_box=BOX, latency_ms=1,
    )


def registry() -> RouteRegistry:
    return RouteRegistry(version="test", routes=[RouteDefinition(
        route_id="CMS1500.patient_name.tesseract.paddleocr.shadow-v1",
        field="patient_name", form="CMS1500", primary_engine="tesseract",
        confirmation_engine="paddleocr", preprocessing_profile="test",
        policy_version="test", benchmark_dataset="holdout-v1", sample_count=200,
        standalone_accuracy=.98, agreement_precision=1, false_agreement_count=0,
        mean_latency_ms=10, cost_per_call_usd=0, cost_status="MEASURED",
        status=RouteLifecycle.SHADOW,
    )])


def test_shadow_route_observes_but_cannot_change_canonical_output():
    sink = InMemoryShadowObservationSink()
    service = ShadowEvaluationService(registry(), sink)
    production = candidate("JANE DOE", "tesseract")

    result = service.observe(
        field_name="patient_name", document_family="CMS1500",
        production_candidate=production,
        shadow_runner=lambda: candidate("WRONG VALUE", "paddleocr"),
        truth_value="JANE DOE", additional_memory_bytes=1024, cost_usd=0,
    )

    assert result.canonical_value == "JANE DOE"
    assert result.canonical_unchanged is True
    assert result.observation.agreement is False
    assert result.observation.shadow_correct is False
    assert result.observation.route_status == "SHADOW"
    assert result.observation.production_candidate.value_sha256 != "JANE DOE"
    assert sink.observations == [result.observation]
