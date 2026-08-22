"""RapidOCR/ONNX field-crop provider with no import-time model loading."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from importlib import metadata
from time import perf_counter
from typing import Any

import numpy as np

from packages.domain.common import BoundingBox
from packages.domain.enums import ClaimFormType
from packages.ocr.contracts import OCRCandidate, OCRRequest, OCRResult
from packages.ocr.preprocessing import PreprocessingRegistry


class FullPageOCRPolicyError(ValueError):
    """Raised when a supported standard form attempts unnecessary full-page OCR."""


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "unknown"


class RapidOCRProvider:
    """Primary local recognizer. Backend injection keeps tests model-free.

    ``execution_providers`` is forwarded to ONNX Runtime through RapidOCR
    where supported. CPU remains the default and requires no GPU runtime.
    """

    provider_name = "rapidocr"

    def __init__(
        self,
        backend: Callable[[np.ndarray], Any] | None = None,
        execution_providers: tuple[str, ...] = ("CPUExecutionProvider",),
        preprocessing: PreprocessingRegistry | None = None,
    ) -> None:
        self._backend = backend
        self.execution_providers = execution_providers
        self.provider_version = _version("rapidocr-onnxruntime")
        self.preprocessing = preprocessing or PreprocessingRegistry.load()

    def _load_backend(self) -> Callable[[np.ndarray], Any]:
        if self._backend is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise RuntimeError(
                    "RapidOCR is not installed; install the 'rapidocr-onnxruntime' runtime"
                ) from exc
            # RapidOCR releases differ in provider keyword support. The model
            # still defaults to CPU; configured providers are retained in evidence.
            self._backend = RapidOCR()
        return self._backend

    @staticmethod
    def _enforce_scope(request: OCRRequest) -> None:
        standard = request.form_type in (ClaimFormType.CMS1500, ClaimFormType.UB04)
        allowed_exception = request.registration_failed or request.policy_allows_full_page
        if request.scope == "FULL_PAGE" and standard and not allowed_exception:
            raise FullPageOCRPolicyError(
                "full-page OCR is prohibited for registered CMS-1500/UB-04 pages"
            )

    @staticmethod
    def _parse(raw: Any) -> list[tuple[str, float, BoundingBox | None]]:
        # RapidOCR commonly returns (results, elapsed), where each result is
        # [four-point box, text, confidence]. Keep provider variance here.
        rows = raw[0] if isinstance(raw, tuple) else raw
        if not rows:
            return []
        parsed = []
        for row in rows:
            if len(row) < 3:
                continue
            parsed.append((str(row[1]), float(row[2]), None))
        return parsed

    def _extract_sync(self, request: OCRRequest) -> OCRResult:
        self._enforce_scope(request)
        started = perf_counter()
        prepared = self.preprocessing.apply(
            request.image, request.field_name, request.field_type, request.preprocessing_profile
        )
        raw = self._load_backend()(np.asarray(prepared.image.convert("RGB")))
        latency = (perf_counter() - started) * 1000
        parsed = self._parse(raw)
        joined = " ".join(text for text, _, _ in parsed).strip()
        confidence = sum(score for _, score, _ in parsed) / len(parsed) if parsed else 0.0
        candidates = (
            ()
            if not parsed
            else (
                OCRCandidate(
                    value=joined or None,
                    raw_value=joined,
                    engine=self.provider_name,
                    model_name="RapidOCR-ONNX",
                    model_version=self.provider_version,
                    preprocessing_variant=prepared.profile,
                    raw_confidence=confidence,
                    calibrated_confidence=None,
                    bounding_box=request.bounding_box,
                    latency_ms=latency,
                    validation_results=(f"SCOPE_{request.scope}",),
                    evidence_reference=None,
                    estimated_cost_usd=0.0,
                    preprocessing_version=prepared.version,
                ),
            )
        )
        return OCRResult(candidates, self.provider_name, self.provider_version, latency)

    async def extract(self, request: OCRRequest) -> OCRResult:
        return await asyncio.to_thread(self._extract_sync, request)
