"""Estimated per-invocation cost, by extraction method -- rough,
configurable proxies (not billed cloud prices) used only to make
`estimated_cost_usd_total` a real, comparable number across routes.
Human review's "cost" is a proxy for reviewer time, not a literal dollar
figure."""

from __future__ import annotations

from packages.domain.enums import ExtractionMethod

DEFAULT_COST_TABLE: dict[ExtractionMethod, float] = {
    ExtractionMethod.CACHE_HIT: 0.0,
    ExtractionMethod.TEMPLATE_RULES: 0.0,
    ExtractionMethod.OPENCV_ALIGNMENT: 0.0001,
    ExtractionMethod.REGIONAL_PADDLEOCR: 0.0010,
    ExtractionMethod.REGIONAL_RAPIDOCR: 0.0002,
    ExtractionMethod.ALTERNATE_PREPROCESS_OCR: 0.0020,
    ExtractionMethod.LAYOUTLMV3: 0.0100,
    ExtractionMethod.TABLE_TRANSFORMER: 0.0100,
    ExtractionMethod.TROCR: 0.0050,
    ExtractionMethod.VLM_FALLBACK: 0.0500,
    ExtractionMethod.HUMAN_REVIEW: 0.7500,
}


def estimated_cost(
    method: ExtractionMethod, cost_table: dict[ExtractionMethod, float] | None = None
) -> float:
    table = cost_table or DEFAULT_COST_TABLE
    return table.get(method, 0.0)
