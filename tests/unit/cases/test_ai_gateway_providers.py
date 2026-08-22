import hashlib

import pytest

from packages.ai_gateway.contracts import FieldResolutionRequest
from packages.ai_gateway.providers import GeminiFlashLiteProvider, TextractProvider


def request():
    crop = b"png-crop"
    return FieldResolutionRequest(
        request_id="r",
        tenant_id="t",
        document_id="d",
        field_name="npi",
        expected_type="npi",
        allowed_pattern=r"\d{10}",
        crop_bytes=crop,
        crop_sha256=hashlib.sha256(crop).hexdigest(),
        ocr_candidates=["1234567893"],
    )


@pytest.mark.asyncio
async def test_gemini_uses_crop_only_strict_schema_and_temperature_zero():
    payloads = []

    async def transport(payload):
        payloads.append(payload)
        return {
            "value": "1234567893",
            "confidence": 0.97,
            "insufficient_evidence": False,
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }

    response = await GeminiFlashLiteProvider("us-central1", transport).resolve(request())
    payload = payloads[0]
    assert payload["generation_config"]["temperature"] == 0
    assert payload["generation_config"]["response_schema"]["additionalProperties"] is False
    assert "document" not in payload
    assert payload["crop"]["sha256"] == request().crop_sha256
    assert response.model == "gemini-2.5-flash-lite"
    assert response.actual_cost_usd > 0


@pytest.mark.asyncio
async def test_textract_normalizes_detect_document_text_lines():
    async def transport(payload):
        assert payload["Feature"] == "DetectDocumentText"
        return {
            "Blocks": [
                {"BlockType": "LINE", "Text": "ABC", "Confidence": 90},
                {"BlockType": "WORD", "Text": "ignored", "Confidence": 99},
            ]
        }

    response = await TextractProvider("us-east-1", transport).resolve(request())
    assert response.value == "ABC"
    assert response.confidence == pytest.approx(0.9)
