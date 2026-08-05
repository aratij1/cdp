"""Production construction for the crop-only, review-gated escalation path."""

from __future__ import annotations

from packages.settings import Settings
from workers.unstructured_extraction.escalation import UnstructuredFieldEscalator
from workers.vlm_fallback.factory import build_vlm_fallback_adapter
from workers.vlm_fallback.service import VLMFallbackService


def build_production_escalator(settings: Settings) -> UnstructuredFieldEscalator:
    if not settings.vlm_enabled:
        return UnstructuredFieldEscalator()
    adapter = build_vlm_fallback_adapter(settings)
    return UnstructuredFieldEscalator(
        vlm=VLMFallbackService(
            adapter,
            model_name=settings.vlm_model_name,
            model_version="1.0",
        )
    )
