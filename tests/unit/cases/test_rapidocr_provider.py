import pytest
from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRRequest
from packages.ocr.rapidocr_provider import FullPageOCRPolicyError, RapidOCRProvider


def _request(**changes):
    values = {
        "document_id": "doc-1",
        "page_number": 1,
        "field_name": "member_id",
        "field_type": "code",
        "form_type": ClaimFormType.CMS1500,
        "image": Image.new("RGB", (120, 40), "white"),
        "bounding_box": BoundingBox(
            x0=10, y0=20, x1=130, y1=60, image_width=850, image_height=1100
        ),
    }
    values.update(changes)
    return OCRRequest(**values)


@pytest.mark.asyncio
async def test_rapidocr_normalizes_provider_output_to_common_result():
    # Place the fake glyph inside source pixels after the five-pixel border and 2x scale.
    backend = lambda image: ([([[14, 14], [34, 14], [34, 24], [14, 24]], "AB123", 0.94)], 0.01)
    result = await RapidOCRProvider(backend=backend).extract(_request())
    assert result.provider == "rapidocr"
    assert result.candidates[0].value == "AB123"
    assert result.candidates[0].estimated_cost_usd == 0
    assert result.candidates[0].bounding_box.x0 == 10
    assert result.candidates[0].preprocessing_variant == "ALPHANUMERIC_CODE"
    assert result.candidates[0].preprocessing_version == "1.1"


@pytest.mark.asyncio
async def test_rapidocr_applies_field_profile_before_backend():
    observed = {}

    def backend(image):
        observed["shape"] = image.shape
        return ([([[14, 14], [34, 14], [34, 24], [14, 24]], "10.00", 0.9)], 0)

    await RapidOCRProvider(backend=backend).extract(
        _request(field_name="total_charge", field_type="amount")
    )
    # NUMERIC v1.1 adds a bounded five-pixel border before the 2x upscale so
    # edge-clipped glyphs are not discarded by thresholding.
    assert observed["shape"][:2] == (100, 260)


@pytest.mark.asyncio
async def test_standard_form_full_page_ocr_is_rejected_before_backend_call():
    called = False

    def backend(_image):
        nonlocal called
        called = True
        return []

    with pytest.raises(FullPageOCRPolicyError):
        await RapidOCRProvider(backend=backend).extract(_request(scope="FULL_PAGE"))
    assert not called


@pytest.mark.asyncio
async def test_registration_failure_explicitly_allows_full_page_fallback():
    provider = RapidOCRProvider(backend=lambda _image: ([], 0.0))
    result = await provider.extract(_request(scope="FULL_PAGE", registration_failed=True))
    assert result.candidates == ()
    assert result.provider == "rapidocr"


def test_cpu_is_the_default_execution_provider():
    assert RapidOCRProvider(backend=lambda _: []).execution_providers == ("CPUExecutionProvider",)
