"""Retries OCR on exactly one failed field's crop, trying each alternate
preprocessing preset in turn and keeping whichever result has the highest
confidence -- including the possibility that none of them beat the
original. Never touches other fields or re-processes the whole page.
"""

from __future__ import annotations

from dataclasses import dataclass
import time

from PIL import Image

from workers.page_detection.text_extraction import TextExtractor, TextLine
from workers.retry.alternate_preprocessing import (
    PRESET_STEPS, PreprocessingContext, PreprocessingRouter, apply_preset,
)


@dataclass(frozen=True)
class RetryResult:
    improved: bool
    preset_name: str | None
    text: str
    confidence: float
    strategies_attempted: tuple[str, ...] = ()


def retry_field(
    page_image: Image.Image,
    region: tuple[int, int, int, int],
    text_extractor: TextExtractor,
    original_confidence: float,
    preprocessing_context: PreprocessingContext | None = None,
    preprocessing_router: PreprocessingRouter | None = None,
) -> RetryResult:
    x0, y0, x1, y1 = region
    crop = page_image.crop((x0, y0, x1, y1))

    best_text = ""
    best_confidence = original_confidence
    best_preset: str | None = None

    strategies = (preprocessing_router or PreprocessingRouter()).select(
        preprocessing_context or PreprocessingContext()
    )
    for preset_name in strategies:
        started_cpu = time.process_time()
        outcome = "no_text"
        steps = PRESET_STEPS[preset_name]
        processed = apply_preset(crop, steps)
        lines = text_extractor.extract(processed)
        if lines:
            text, confidence = _combine_lines(lines)
            outcome = "improved" if confidence > best_confidence else "not_improved"
            if confidence > best_confidence:
                best_text, best_confidence, best_preset = text, confidence, preset_name
        from packages.observability.metrics import preprocessing_strategy_cpu_seconds
        preprocessing_strategy_cpu_seconds.labels(
            strategy=preset_name, outcome=outcome
        ).observe(max(0.0, time.process_time() - started_cpu))

    return RetryResult(
        improved=best_preset is not None,
        preset_name=best_preset,
        text=best_text,
        confidence=best_confidence,
        strategies_attempted=strategies,
    )


def _combine_lines(lines: list[TextLine]) -> tuple[str, float]:
    ordered = sorted(lines, key=lambda l: (l.y0, l.x0))
    text = " ".join(l.text for l in ordered)
    avg_confidence = sum(l.confidence for l in ordered) / len(ordered)
    return text, avg_confidence
