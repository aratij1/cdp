from __future__ import annotations

import io
import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from packages.ocr_cache import InMemoryOCRCache, OCRCacheEntry, ocr_cache_key
from workers.page_detection.text_extraction import TextLine


@dataclass(frozen=True)
class OCRCallRecord:
    document_id: str | None
    page_id: str | None
    route: str | None
    field: str | None
    engine: str
    crop_hash: str
    preprocessing_profile: str
    attempt_number: int
    reason: str
    cache_hit: bool
    latency_ms: float
    cpu_ms: float
    candidate_produced: bool


class JsonlOCRAuditSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path); self._lock = threading.Lock()

    def __call__(self, record: OCRCallRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(record), separators=(",", ":")) + "\n")


def _png(image: Image.Image) -> bytes:
    buffer=io.BytesIO(); image.save(buffer,format="PNG"); return buffer.getvalue()


class CachedInstrumentedTextExtractor:
    """Drop-in TextExtractor that preserves cached original OCR evidence."""
    def __init__(self, inner, *, cache: InMemoryOCRCache | None = None, audit_sink=None,
                 preprocessing_version: str = "document-preparation-v1") -> None:
        self.inner=inner; self.cache=cache or InMemoryOCRCache(); self.audit_sink=audit_sink
        self.preprocessing_version=preprocessing_version
        self._context = threading.local()

    def set_context(self, **values) -> None:
        current = getattr(self._context, "values", {})
        self._context.values = {**current, **values}

    @property
    def engine_name(self): return getattr(self.inner,"engine_name",type(self.inner).__name__)
    @property
    def model_name(self): return getattr(self.inner,"model_name",self.engine_name)
    @property
    def model_version(self): return getattr(self.inner,"model_version","unknown")

    def _extract(self, crop: Image.Image, *, context: dict, full_page: bool):
        payload=_png(crop); configuration={"scope":"FULL_PAGE" if full_page else "REGION",
            "psm":getattr(self.inner,"psm",None)}
        key=ocr_cache_key(crop_bytes=payload,engine=self.engine_name,
            model_version=self.model_version,preprocessing_version=self.preprocessing_version,
            configuration=configuration)
        started=time.perf_counter(); cpu=time.process_time(); cached=self.cache.get(key)
        if cached is None:
            lines=(self.inner.extract(crop) if full_page else
                   self.inner.extract_region(crop,0,0,crop.width,crop.height))
            entry=self.cache.put_if_absent(key,OCRCacheEntry(tuple(lines),f"ocr-cache:{key}"))
            cache_hit=False
        else:
            entry=cached; cache_hit=True
        wall_ms=(time.perf_counter()-started)*1000; cpu_ms=(time.process_time()-cpu)*1000
        if self.audit_sink:
            self.audit_sink(OCRCallRecord(
                document_id=context.get("document_id"),page_id=context.get("page_id"),
                route=context.get("route"),field=context.get("field"),engine=self.engine_name,
                crop_hash=key[:64],preprocessing_profile=self.preprocessing_version,
                attempt_number=context.get("attempt_number",1),reason=context.get("reason","PRIMARY"),
                cache_hit=cache_hit,latency_ms=wall_ms,cpu_ms=cpu_ms,
                candidate_produced=bool(entry.value)))
        return list(entry.value)

    def extract(self,image:Image.Image):
        return self._extract(image,context=getattr(self._context,"values",{}),full_page=True)

    def extract_region(self,image:Image.Image,x0:int,y0:int,x1:int,y1:int):
        crop=image.crop((x0,y0,x1,y1)); lines=self._extract(
            crop,context=getattr(self._context,"values",{}),full_page=False)
        return [TextLine(line.text,line.x0+x0,line.y0+y0,line.x1+x0,line.y1+y0,line.confidence)
                for line in lines]
