"""LayoutLMv3 integration point for Bundle D (unstructured claim
documents with a configured extraction schema) and as an escalation step
for standard-form fields that keep failing regional OCR.

Not trained/wired: LayoutLMv3 needs a fine-tuned checkpoint per document
schema (there's no generic "extract these named fields" LayoutLMv3 model)
plus `torch`/`transformers`, which -- like `paddlepaddle` and
`torchvision` for MobileNetV3 -- isn't installed on every dev host. The
`LayoutModelAdapter` protocol is what `packages.model_router` routes
callers to; `LayoutLMv3Adapter` raises `ModelNotAvailableError` until a
checkpoint is configured, exactly like `MobileNetV3PageClassifier`
(workers/page_detection/mobilenet_classifier.py) and
`PaddleOCRTextExtractor` (workers/page_detection/text_extraction.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class LayoutFieldResult:
    field_name: str
    value: str
    confidence: float


class ModelNotAvailableError(RuntimeError):
    pass


class LayoutModelAdapter(Protocol):
    def extract(self, image: Image.Image, field_schema: list[str]) -> list[LayoutFieldResult]: ...


class LayoutLMv3Adapter:
    def __init__(self, checkpoint_path: str | None = None) -> None:
        self._checkpoint_path = checkpoint_path

    # A checkpoint directory is not evidence of a functioning implementation.
    inference_implemented = False

    def extract(self, image: Image.Image, field_schema: list[str]) -> list[LayoutFieldResult]:
        raise ModelNotAvailableError("FALLBACK_RUNTIME_NOT_IMPLEMENTED")
