"""VLM adapter safety properties (docs/ARCHITECTURE.md §11): temperature
0, strict JSON schema, unsupported-field rejection, insufficient_evidence
handling, disabled-by-default, and the service-layer "failed fields only,
never overwrite validated fields" invariant. All against a mocked HTTP
transport -- no real vLLM server involved.
"""

import json

import httpx
import pytest
from PIL import Image

from packages.domain.common import BoundingBox
from packages.domain.enums import ExtractionMethod, ValidationStatus
from packages.domain.extraction import ExtractedField
from packages.retraining import CorrectionMemory
from workers.vlm_fallback.adapter import (
    OpenAIVLLMAdapter,
    VLMDisabledError,
    VLMResponseError,
)
from workers.vlm_fallback.schema import VLMFieldRequest
from workers.vlm_fallback.service import VLMFallbackService

CAPTURED_REQUESTS: list[dict] = []


def _mock_transport(response_fields: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        CAPTURED_REQUESTS.append(json.loads(request.content))
        body = {
            "choices": [
                {"message": {"content": json.dumps({"fields": response_fields})}}
            ]
        }
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _clear_captured():
    CAPTURED_REQUESTS.clear()
    yield


def _adapter(response_fields: list[dict], enabled: bool = True) -> OpenAIVLLMAdapter:
    client = httpx.Client(transport=_mock_transport(response_fields))
    return OpenAIVLLMAdapter(
        endpoint="http://fake-vllm:8001/v1",
        model_name="qwen2.5-vl-3b-instruct",
        enabled=enabled,
        http_client=client,
    )


def test_disabled_adapter_raises_before_any_http_call():
    adapter = _adapter([], enabled=False)
    with pytest.raises(VLMDisabledError):
        adapter.extract_fields({}, [VLMFieldRequest(field_name="x", field_type="text", expected_description="x")])
    assert CAPTURED_REQUESTS == []


def test_request_uses_temperature_zero_and_strict_json_schema():
    adapter = _adapter([{"field_name": "npi", "value": "1396827531", "confidence": 0.9, "insufficient_evidence": False}])
    adapter.extract_fields(
        {"npi": b"fake-png-bytes"},
        [VLMFieldRequest(field_name="npi", field_type="npi", expected_description="Rendering provider NPI")],
    )
    assert len(CAPTURED_REQUESTS) == 1
    payload = CAPTURED_REQUESTS[0]
    assert payload["temperature"] == 0
    assert payload["response_format"]["type"] == "json_schema"
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["fields"]["items"]["additionalProperties"] is False


def test_only_crop_images_are_sent_never_a_full_page():
    adapter = _adapter([{"field_name": "npi", "value": "1", "confidence": 0.9, "insufficient_evidence": False}])
    adapter.extract_fields(
        {"npi": b"crop-bytes-only"},
        [VLMFieldRequest(field_name="npi", field_type="npi", expected_description="x")],
    )
    content = CAPTURED_REQUESTS[0]["messages"][0]["content"]
    image_parts = [c for c in content if c["type"] == "image_url"]
    assert len(image_parts) == 1  # exactly the one crop supplied, nothing else


def test_parses_valid_response_into_field_results():
    adapter = _adapter(
        [{"field_name": "npi", "value": "1396827531", "confidence": 0.92, "insufficient_evidence": False}]
    )
    results = adapter.extract_fields(
        {"npi": b"x"}, [VLMFieldRequest(field_name="npi", field_type="npi", expected_description="x")]
    )
    assert len(results) == 1
    assert results[0].value == "1396827531"
    assert results[0].confidence == 0.92


def test_insufficient_evidence_is_preserved_not_guessed():
    adapter = _adapter(
        [{"field_name": "npi", "value": None, "confidence": 0.0, "insufficient_evidence": True}]
    )
    results = adapter.extract_fields(
        {"npi": b"x"}, [VLMFieldRequest(field_name="npi", field_type="npi", expected_description="x")]
    )
    assert results[0].insufficient_evidence
    assert results[0].value is None


def test_unrequested_field_in_response_raises():
    adapter = _adapter(
        [{"field_name": "totally_unrequested_field", "value": "x", "confidence": 0.9, "insufficient_evidence": False}]
    )
    with pytest.raises(VLMResponseError):
        adapter.extract_fields(
            {"npi": b"x"}, [VLMFieldRequest(field_name="npi", field_type="npi", expected_description="x")]
        )


def test_empty_request_list_short_circuits_without_http_call():
    adapter = _adapter([])
    results = adapter.extract_fields({}, [])
    assert results == []
    assert CAPTURED_REQUESTS == []


def test_field_scoped_correction_memory_is_injected_as_system_context(tmp_path):
    memory_path = tmp_path / "corrections.jsonl"
    memory_path.write_text(json.dumps({
        "field_name": "npi", "previous_value": "a 1396827531",
        "corrected_value": "1396827531", "tenant_id": "default",
    }) + "\n")
    client = httpx.Client(transport=_mock_transport([
        {"field_name": "npi", "value": "1396827531", "confidence": .9,
         "insufficient_evidence": False, "citation": None}
    ]))
    adapter = OpenAIVLLMAdapter(
        endpoint="http://fake", model_name="test", enabled=True, http_client=client,
        correction_memory=CorrectionMemory(memory_path),
    )
    adapter.extract_fields({}, [VLMFieldRequest(
        field_name="npi", field_type="npi", expected_description="NPI"
    )])
    messages = CAPTURED_REQUESTS[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "a 1396827531" in messages[0]["content"]
    assert "1396827531" in messages[0]["content"]
    assert "never copy" in messages[0]["content"]


# --- service layer -----------------------------------------------------------------


def _bbox() -> BoundingBox:
    return BoundingBox(x0=0, y0=0, x1=10, y1=10, image_width=100, image_height=100)


def _field(name: str, status: ValidationStatus, raw: str = "x") -> ExtractedField:
    return ExtractedField(
        field_name=name,
        raw_value=raw,
        confidence=0.5,
        page_number=1,
        bounding_box=_bbox(),
        extraction_method=ExtractionMethod.REGIONAL_PADDLEOCR,
        validation_status=status,
    )


def test_service_never_requests_already_valid_fields():
    adapter = _adapter([{"field_name": "bad_field", "value": "y", "confidence": 0.9, "insufficient_evidence": False}])
    service = VLMFallbackService(adapter, model_name="qwen2.5-vl-3b-instruct", model_version="1.0")

    fields = [
        _field("good_field", ValidationStatus.VALID),
        _field("bad_field", ValidationStatus.INVALID),
    ]
    crops = {"good_field": Image.new("L", (10, 10)), "bad_field": Image.new("L", (10, 10))}

    service.request_for_failed_fields(fields, crops, field_types={}, descriptions={})

    # the crop dict sent to the adapter (and therefore to the wire) must
    # only ever contain the failed field
    image_parts = [c for c in CAPTURED_REQUESTS[0]["messages"][0]["content"] if c["type"] == "image_url"]
    assert len(image_parts) == 1
    assert image_parts[0]["detail"] == "bad_field"


def test_service_returns_no_evidence_when_nothing_failed():
    adapter = _adapter([])
    service = VLMFallbackService(adapter, model_name="m", model_version="1")
    fields = [_field("good_field", ValidationStatus.VALID)]

    evidence = service.request_for_failed_fields(fields, {}, field_types={}, descriptions={})

    assert evidence == []
    assert CAPTURED_REQUESTS == []  # never even calls the adapter


def test_service_skips_insufficient_evidence_results():
    adapter = _adapter([{"field_name": "bad_field", "value": None, "confidence": 0.0, "insufficient_evidence": True}])
    service = VLMFallbackService(adapter, model_name="m", model_version="1")
    fields = [_field("bad_field", ValidationStatus.NEEDS_REVIEW)]
    crops = {"bad_field": Image.new("L", (10, 10))}

    evidence = service.request_for_failed_fields(fields, crops, field_types={}, descriptions={})

    assert evidence == []


def test_service_produces_vlm_field_evidence_for_usable_results():
    adapter = _adapter(
        [{"field_name": "bad_field", "value": "1396827531", "confidence": 0.9, "insufficient_evidence": False}]
    )
    service = VLMFallbackService(adapter, model_name="qwen2.5-vl-3b-instruct", model_version="1.0")
    fields = [_field("bad_field", ValidationStatus.INVALID)]
    crops = {"bad_field": Image.new("L", (10, 10))}

    evidence = service.request_for_failed_fields(fields, crops, field_types={}, descriptions={})

    assert len(evidence) == 1
    assert evidence[0].source == ExtractionMethod.VLM_FALLBACK
    assert evidence[0].raw_text == "1396827531"
    assert evidence[0].model_name == "qwen2.5-vl-3b-instruct"
