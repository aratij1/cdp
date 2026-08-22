"""Version-aware content addressing for OCR work products."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass


def ocr_cache_key(*, crop_bytes: bytes, engine: str, model_version: str,
                  preprocessing_version: str, configuration: dict) -> str:
    digest = hashlib.sha256()
    digest.update(crop_bytes)
    for value in (engine, model_version, preprocessing_version,
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

    def get(self, key: str) -> OCRCacheEntry | None:
        with self._lock: return self._values.get(key)

    def put_if_absent(self, key: str, entry: OCRCacheEntry) -> OCRCacheEntry:
        with self._lock: return self._values.setdefault(key, entry)
