"""PHI-free timing and invocation accounting for the shadow architecture."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

STAGES = (
    "decode_ms",
    "render_ms",
    "preprocess_ms",
    "form_identity_ms",
    "full_page_ocr_ms",
    "spatial_reasoning_ms",
    "regional_ocr_ms",
    "candidate_assembly_ms",
    "claim_graph_ms",
    "constraint_engine_ms",
    "risk_scoring_ms",
    "llm_ms",
    "serialization_ms",
)
T = TypeVar("T")


@dataclass
class OCRInvocationLedger:
    full_page_ocr_calls: int = 0
    regional_ocr_calls: int = 0
    challenger_calls: int = 0
    cache_hits: int = 0
    repeated_full_page_attempts: int = 0
    _full_result: Any = field(default=None, repr=False)
    _full_key: str | None = None
    _completed: bool = False

    def full_page(self, key: str, invoke: Callable[[], T]) -> T:
        if self._completed:
            if self._full_key != key:
                raise ValueError("PAGE_PERCEPTION_KEY_CHANGED")
            self.repeated_full_page_attempts += 1
            self.cache_hits += 1
            return self._full_result
        self.full_page_ocr_calls += 1
        self._full_result = invoke()
        self._full_key, self._completed = key, True
        return self._full_result

    def use_validated_cache(self, key: str, value: T, *, provenance_valid: bool) -> T:
        if not provenance_valid:
            raise ValueError("OCR_CACHE_PROVENANCE_INVALID")
        if self._completed and self._full_key != key:
            raise ValueError("PAGE_PERCEPTION_KEY_CHANGED")
        self.cache_hits += 1
        self._full_key, self._full_result, self._completed = key, value, True
        return value

    def regional(self, invoke: Callable[[], T], *, unresolved: bool, challenger: bool = False) -> T:
        if not unresolved:
            raise ValueError("REGIONAL_OCR_REQUIRES_UNRESOLVED_FIELD")
        if challenger:
            self.challenger_calls += 1
        else:
            self.regional_ocr_calls += 1
        return invoke()

    def diagnostics(self) -> dict[str, int]:
        return {
            k: getattr(self, k)
            for k in (
                "full_page_ocr_calls",
                "regional_ocr_calls",
                "challenger_calls",
                "cache_hits",
                "repeated_full_page_attempts",
            )
        }


@dataclass
class PerformanceProfile:
    stages: dict[str, float | None] = field(default_factory=lambda: dict.fromkeys(STAGES))
    started: float = field(default_factory=time.perf_counter)
    active: bool = False

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        if stage not in self.stages or self.active:
            raise ValueError("INVALID_OR_OVERLAPPING_STAGE")
        self.active = True
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[stage] = (self.stages[stage] or 0) + (time.perf_counter() - start) * 1000
            self.active = False

    def diagnostics(self) -> dict[str, Any]:
        total = (time.perf_counter() - self.started) * 1000
        return {
            **self.stages,
            "total_ms": total,
            "unattributed_ms": max(0, total - sum(v or 0 for v in self.stages.values())),
            "unmeasured_stages": [k for k, v in self.stages.items() if v is None],
        }
