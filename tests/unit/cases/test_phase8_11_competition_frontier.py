from dataclasses import replace

import pytest
from PIL import Image

from packages.domain.common import BoundingBox
from packages.ocr import OCRCandidate, OCRExecutionService, OCRRequest, OCRResult
from packages.page_observation import PageObservationCache, PageObservationService
from workers.page_detection.text_extraction import TextLine


class CountingFullPageOCR:
    model_version = "benchmark-fixture-v1"

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, _image):
        self.calls += 1
        return [TextLine("PATIENT NAME", 10, 10, 100, 30, 0.99)]


class CountingProvider:
    provider_name = "fixture"
    provider_version = "v1"

    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, request: OCRRequest) -> OCRResult:
        self.calls += 1
        candidate = OCRCandidate(
            value="JANE DOE",
            raw_value="JANE DOE",
            raw_confidence=0.99,
            calibrated_confidence=0.99,
            engine="fixture",
            model_name="fixture",
            model_version="v1",
            preprocessing_variant="NONE",
            bounding_box=request.bounding_box,
            latency_ms=1.0,
        )
        return OCRResult(
            candidates=(candidate,), provider="fixture", provider_version="v1", latency_ms=1.0
        )


def _request() -> OCRRequest:
    return OCRRequest(
        document_id="doc-1",
        page_number=1,
        form_type="CMS1500",
        field_name="patient_name",
        field_type="text",
        image=Image.new("RGB", (100, 50), "white"),
        bounding_box=BoundingBox(x0=0, y0=0, x1=100, y1=50, image_width=100, image_height=50),
        scope="FIELD_CROP",
    )


def test_benchmark_mode_bypasses_page_observation_output_cache():
    engine = CountingFullPageOCR()
    service = PageObservationService(
        engine,
        preprocessing_version="fixture-v1",
        cache=PageObservationCache(),
        benchmark_mode=True,
    )
    image = Image.new("RGB", (200, 100), "white")

    first = service.observe("page-1", image)
    second = service.observe("page-1", image)

    assert first is not second
    assert engine.calls == 2


@pytest.mark.asyncio
async def test_benchmark_mode_bypasses_ocr_result_cache():
    provider = CountingProvider()
    service = OCRExecutionService(benchmark_mode=True)

    first = await service.execute(provider, _request())
    second = await service.execute(provider, replace(_request(), document_id="doc-1"))

    assert not first.cache_hit
    assert not second.cache_hit
    assert provider.calls == 2
