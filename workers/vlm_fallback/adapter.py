"""VLM adapter over a vLLM-compatible OpenAI `/chat/completions` endpoint
(e.g. serving Qwen2.5-VL-3B-Instruct). Safety properties required by
docs/ARCHITECTURE.md §11, each enforced in code, not just documented:

- temperature 0            -> hardcoded in the request payload
- strict JSON               -> `response_format: json_schema` with
                                `additionalProperties: false` throughout
- prohibit unsupported fields -> requested-vs-returned field name check
                                  after parsing; extra keys also rejected
                                  by `VLMFieldResult`'s `extra="forbid"`
- crop-only evidence        -> `extract_fields` takes crops, never a
                                full-page image; there is no "send the
                                whole page" code path
- insufficient_evidence      -> part of the response schema; the adapter
                                does not fabricate a value when set
- disabled by configuration  -> raises `VLMDisabledError` unless
                                constructed with `enabled=True`

"Never overwrite high-confidence validated fields" and "pass all output
through deterministic validation" are enforced one layer up, in
`service.py` (which filters to failed fields before ever calling this
adapter, and hands results back as ordinary `FieldEvidence` that flows
through the same `ValidationEngine` as any other extraction) -- not here,
because this class only knows about one HTTP call, not the claim's state.
"""

from __future__ import annotations

import base64
import json
from typing import Protocol

import httpx

from packages.retraining import CorrectionMemory

from workers.vlm_fallback.schema import VLMFieldRequest, VLMFieldResult, build_response_json_schema


class VLMDisabledError(RuntimeError):
    pass


class VLMResponseError(ValueError):
    pass


class VLMAdapter(Protocol):
    def extract_fields(
        self, crops: dict[str, bytes], requests: list[VLMFieldRequest]
    ) -> list[VLMFieldResult]: ...


class OpenAIVLLMAdapter:
    def __init__(
        self,
        endpoint: str,
        model_name: str,
        enabled: bool,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
        correction_memory: CorrectionMemory | None = None,
        tenant_id: str = "default",
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model_name = model_name
        self._enabled = enabled
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._correction_memory = correction_memory
        self._tenant_id = tenant_id

    def extract_fields(
        self, crops: dict[str, bytes], requests: list[VLMFieldRequest]
    ) -> list[VLMFieldResult]:
        if not self._enabled:
            raise VLMDisabledError(
                "VLM adapter is disabled by configuration (VLM_ENABLED=false) -- "
                "this call should not have been made"
            )
        if not requests:
            return []

        payload = {
            "model": self._model_name,
            "temperature": 0,
            "messages": self._build_messages(crops, requests),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "field_extraction",
                    "schema": build_response_json_schema([r.field_name for r in requests]),
                    "strict": True,
                },
            },
        }
        response = self._client.post(f"{self._endpoint}/chat/completions", json=payload)
        response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        results = [VLMFieldResult.model_validate(item) for item in parsed.get("fields", [])]

        requested_names = {r.field_name for r in requests}
        returned_names = {r.field_name for r in results}
        unsupported = returned_names - requested_names
        if unsupported:
            raise VLMResponseError(f"VLM returned unrequested field(s): {sorted(unsupported)}")

        return results

    def _build_messages(
        self, crops: dict[str, bytes], requests: list[VLMFieldRequest]
    ) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": self._build_prompt(requests)}]
        for field_name, image_bytes in crops.items():
            encoded = base64.b64encode(image_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    "detail": field_name,  # crop identifier, not used by the model
                }
            )
        messages: list[dict] = []
        exemplar_lines: list[str] = []
        if self._correction_memory is not None:
            for request in requests:
                for example in self._correction_memory.exemplars(request.field_name, self._tenant_id):
                    exemplar_lines.append(
                        f"- {request.field_name}: OCR observed {example['observed']!r}; "
                        f"approved correction {example['corrected']!r}"
                    )
        if exemplar_lines:
            messages.append({
                "role": "system",
                "content": (
                    "Approved reviewer corrections for the same tenant and field route are "
                    "examples only. Use them to recognize formatting/error patterns, never copy "
                    "a value without visible crop evidence, and still abstain when uncertain.\n" +
                    "\n".join(exemplar_lines)
                ),
            })
        messages.append({"role": "user", "content": content})
        return messages

    def _build_prompt(self, requests: list[VLMFieldRequest]) -> str:
        lines = [
            (
                "Extract the following fields using ONLY the evidence visible in the "
                "provided image crop(s). Do not guess. If the evidence is unclear, "
                "cut off, or absent, set insufficient_evidence=true and value=null "
                "for that field rather than inventing a value."
            ),
            "",
        ]
        for r in requests:
            lines.append(f"- {r.field_name} ({r.field_type}): {r.expected_description}")
            if r.prior_ocr_candidates:
                lines.append(f"  Prior OCR candidates (may be wrong): {r.prior_ocr_candidates}")
        return "\n".join(lines)


class AzureOpenAIVisionAdapter(OpenAIVLLMAdapter):
    """Azure OpenAI chat-completions adapter with crop-only payloads.

    Credentials are supplied at runtime and are never persisted on the adapter.
    """

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_version: str,
        api_key: str,
        enabled: bool,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
        correction_memory: CorrectionMemory | None = None,
        tenant_id: str = "default",
    ) -> None:
        super().__init__(
            endpoint, deployment, enabled, http_client, timeout_seconds,
            correction_memory, tenant_id,
        )
        self._deployment = deployment
        self._api_version = api_version
        self._api_key = api_key
        self.last_usage: dict[str, int] = {}

    def extract_fields(
        self, crops: dict[str, bytes], requests: list[VLMFieldRequest]
    ) -> list[VLMFieldResult]:
        if not self._enabled:
            raise VLMDisabledError("Azure VLM shadow adapter is disabled")
        if not requests:
            return []
        payload = {
            "temperature": 0,
            "messages": self._build_messages(crops, requests),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "field_extraction",
                    "schema": build_response_json_schema(
                        [request.field_name for request in requests]
                    ),
                    "strict": True,
                },
            },
        }
        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}/chat/completions"
            f"?api-version={self._api_version}"
        )
        response = self._client.post(
            url, json=payload, headers={"api-key": self._api_key}
        )
        if response.is_error:
            try:
                error = response.json().get("error", {})
                detail = {
                    "status": response.status_code,
                    "code": error.get("code"),
                    "message": str(error.get("message", "Azure request rejected"))[:500],
                }
            except (ValueError, AttributeError):
                detail = {"status": response.status_code, "code": None,
                          "message": "Azure request rejected"}
            raise VLMResponseError(json.dumps(detail))
        response_payload = response.json()
        usage = response_payload.get("usage", {})
        self.last_usage = {
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }
        parsed = json.loads(response_payload["choices"][0]["message"]["content"])
        results = [
            VLMFieldResult.model_validate(item) for item in parsed.get("fields", [])
        ]
        requested = {request.field_name for request in requests}
        unsupported = {result.field_name for result in results} - requested
        if unsupported:
            raise VLMResponseError(
                f"VLM returned unrequested field(s): {sorted(unsupported)}"
            )
        return results

    def _build_messages(
        self, crops: dict[str, bytes], requests: list[VLMFieldRequest]
    ) -> list[dict]:
        messages = super()._build_messages(crops, requests)
        for part in messages[0]["content"]:
            if part["type"] == "image_url":
                part["image_url"]["detail"] = "high"
        return messages

class FlorenceVLMAdapter:
    def __init__(self, model_name: str, enabled: bool) -> None:
        self._model_name = model_name
        self._enabled = enabled
        from workers.cascade.florence2_adapter import Florence2Adapter
        self._florence = Florence2Adapter(model_name=model_name)

    def extract_fields(
        self, crops: dict[str, bytes], requests: list[VLMFieldRequest]
    ) -> list[VLMFieldResult]:
        if not self._enabled:
            raise VLMDisabledError("VLM adapter is disabled")
        import io
        from PIL import Image

        results = []
        for req in requests:
            crop_bytes = crops.get(req.field_name)
            if not crop_bytes:
                continue
            image = Image.open(io.BytesIO(crop_bytes))
            result = self._florence.recognize(image)
            results.append(
                VLMFieldResult(
                    field_name=req.field_name,
                    value=result.text,
                    insufficient_evidence=result.insufficient_evidence,
                    confidence=result.confidence,
                    citation=None,
                )
            )
        return results
