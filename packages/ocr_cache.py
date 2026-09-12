"""Version-aware content addressing for OCR work products."""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import Future
from collections.abc import Callable
from dataclasses import dataclass


def ocr_cache_key(*, crop_bytes: bytes, engine: str, model_version: str,
                  preprocessing_version: str, configuration: dict,
                  page_hash: str | None = None,
                  region_bbox: tuple[int, int, int, int] | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(crop_bytes)
    for value in (page_hash or "content-addressed-page", str(region_bbox or "FULL_PAGE"),
                  engine, model_version, preprocessing_version,
                  json.dumps(configuration, sort_keys=True, separators=(",", ":"))):
        digest.update(b"\0"); digest.update(value.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True)
class OCRCacheEntry:
    value: object
    evidence_reference: str


class InMemoryOCRCache:
    """Process-local lifecycle cache; callers may replace it with Redis."""
    def __init__(self) -> None:
        self._values: dict[str, OCRCacheEntry] = {}
        self._lock = threading.Lock()
        self._pending: dict[str, Future] = {}

    def get(self, key: str) -> OCRCacheEntry | None:
        with self._lock: return self._values.get(key)

    def put_if_absent(self, key: str, entry: OCRCacheEntry) -> OCRCacheEntry:
        with self._lock: return self._values.setdefault(key, entry)

    def get_or_compute(self, key: str, compute: Callable[[], OCRCacheEntry]) -> tuple[OCRCacheEntry, bool]:
        """Coalesce concurrent identical requests; failures do not poison the cache."""
        with self._lock:
            if key in self._values:
                return self._values[key], True
            pending = self._pending.get(key)
            owner = pending is None
            if owner:
                pending = Future()
                self._pending[key] = pending
        if not owner:
            return pending.result(), True
        try:
            entry = self.put_if_absent(key, compute())
            pending.set_result(entry)
            return entry, False
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)
