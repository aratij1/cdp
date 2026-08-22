"""Transport-injected Gemini/Vertex and Textract providers.

SDK-specific credentials and clients stay in composition roots. Business logic
depends only on these provider contracts and never imports a cloud SDK.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from packages.ai_gateway.contracts import FieldResolutionRequest, FieldResolutionResponse

AsyncTransport = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class GeminiProvider:
    provider_name = "vertex_ai_gemini"

    def __init__(
        self,
        model_name: str,
        model_version: str,
        region: str,
        transport: AsyncTransport,
        input_cost_per_million: float,
        output_cost_per_million: float,
    ) -> None:
        self.model_name = model_name
        self.model_version = model_version
        self.region = region
        self._transport = transport
        self._input_cost = input_cost_per_million
        self._output_cost = output_cost_per_million

    async def resolve(self, request: FieldResolutionRequest) -> FieldResolutionResponse:
        started = monotonic()
        payload = {
            "model": self.model_name,
            "region": self.region,
            "generation_config": {
                "temperature": 0,
                "response_mime_type": "application/json",
                "response_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["value", "confidence", "insufficient_evidence"],
                    "properties": {
                        "value": {"type": ["string", "null"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "insufficient_evidence": {"type": "boolean"},
                    },
                },
            },
            "field": {
                "name": request.field_name,
                "expected_type": request.expected_type,
                "allowed_pattern": request.allowed_pattern,
                "nearby_label": request.nearby_label,
                "ocr_candidates": request.ocr_candidates,
                "validation_errors": request.validation_errors,
                "task": "Resolve only the text visible in this field crop; abstain if unclear.",
            },
            "crop": {
                "mime_type": "image/png",
                "data": base64.b64encode(request.crop_bytes).decode("ascii"),
                "sha256": request.crop_sha256,
            },
        }
        raw = await self._transport(payload)
        allowed = {"value", "confidence", "insufficient_evidence", "usage"}
        unexpected = set(raw) - allowed
        required = {"value", "confidence", "insufficient_evidence"}
        missing = required - set(raw)
        if unexpected or missing:
            raise ValueError(
                f"invalid Gemini structured response; missing={sorted(missing)}, "
                f"unexpected={sorted(unexpected)}"
            )
        usage = raw.get("usage", {})
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        cost = (input_tokens * self._input_cost + output_tokens * self._output_cost) / 1_000_000
        return FieldResolutionResponse(
            value=raw["value"],
            confidence=raw["confidence"],
            insufficient_evidence=raw["insufficient_evidence"],
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_cost_usd=cost,
            latency_ms=(monotonic() - started) * 1000,
        )


class GeminiFlashLiteProvider(GeminiProvider):
    def __init__(self, region: str, transport: AsyncTransport) -> None:
        super().__init__("gemini-2.5-flash-lite", "2.5", region, transport, 0.10, 0.40)


class GeminiFlashProvider(GeminiProvider):
    def __init__(self, region: str, transport: AsyncTransport) -> None:
        super().__init__("gemini-2.5-flash", "2.5", region, transport, 0.30, 2.50)


class GeminiProProvider(GeminiProvider):
    def __init__(self, region: str, transport: AsyncTransport) -> None:
        super().__init__("gemini-2.5-pro", "2.5", region, transport, 1.25, 10.00)


class TextractProvider:
    provider_name = "aws_textract"
    model_name = "DetectDocumentText"
    model_version = "2018-06-27"

    def __init__(
        self, region: str, transport: AsyncTransport, page_cost_usd: float = 0.0015
    ) -> None:
        self.region = region
        self._transport = transport
        self._page_cost = page_cost_usd

    async def resolve(self, request: FieldResolutionRequest) -> FieldResolutionResponse:
        started = monotonic()
        raw = await self._transport(
            {
                "Document": {"Bytes": request.crop_bytes},
                "Feature": "DetectDocumentText",
                "Region": self.region,
                "CropSHA256": request.crop_sha256,
            }
        )
        blocks = [block for block in raw.get("Blocks", []) if block.get("BlockType") == "LINE"]
        value = " ".join(str(block.get("Text", "")) for block in blocks).strip()
        confidence = (
            sum(float(block.get("Confidence", 0)) for block in blocks) / (100 * len(blocks))
            if blocks
            else 0.0
        )
        return FieldResolutionResponse(
            value=value or None,
            confidence=confidence,
            insufficient_evidence=not bool(value),
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            actual_cost_usd=self._page_cost,
            latency_ms=(monotonic() - started) * 1000,
        )
