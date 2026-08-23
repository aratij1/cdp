"""OCR text extraction interface.

`paddlepaddle` (PaddleOCR's backend) has no wheel for every dev
environment (confirmed: no match for Python 3.14 on this project's host --
see docs/DATASET_FINDINGS.md-adjacent notes in docs/ARCHITECTURE.md §12),
so the real OCR engine is imported lazily and only inside the Docker image
that installs the `[ml]` extras group (Python 3.11). Everything in
`workers.page_detection`/`workers.standard_form_extraction` depends on the
`TextExtractor` protocol below, never on `paddleocr` directly, so routing
and field-processor logic is fully unit-testable with a fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float


class TextExtractor(Protocol):
    def extract(self, image: Image.Image) -> list[TextLine]:
        """Full-page OCR, used for anchor-phrase verification."""
        ...

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        """Regional OCR, used by standard_form_extraction on aligned pages."""
        ...


class ModelNotAvailableError(RuntimeError):
    pass


class RapidOCRTextExtractor:
    """RapidOCR adapter restricted to explicitly supplied field regions."""

    engine_name = "rapidocr"
    model_name = "RapidOCR-ONNX"

    def __init__(self, backend=None, model_version: str = "rapidocr-onnxruntime") -> None:
        self._engine = backend
        self._regional_upscale = backend is None
        self._initialization_count = 1 if backend is not None else 0
        self.model_version = model_version

    @property
    def initialization_count(self) -> int:
        return self._initialization_count

    def _load(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise ModelNotAvailableError(
                    "rapidocr-onnxruntime is not installed -- install the '[ocr]' extra"
                ) from exc
            self._engine = RapidOCR()
            self._initialization_count += 1
        return self._engine

    def extract(self, image: Image.Image) -> list[TextLine]:
        raise ValueError("RapidOCR primary is region-only for supported standard forms")

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        import numpy as np

        crop = image.crop((x0, y0, x1, y1)).convert("RGB")
        scale = 3 if self._regional_upscale and max(crop.size) < 900 else 1
        working = crop if scale == 1 else crop.resize(
            (crop.width*scale, crop.height*scale), Image.Resampling.LANCZOS
        )
        raw = self._load()(np.asarray(working))
        rows = raw[0] if isinstance(raw, tuple) else raw
        lines: list[TextLine] = []
        for row in rows or []:
            if len(row) < 3:
                continue
            box, text, confidence = row[0], str(row[1]), float(row[2])
            xs, ys = [point[0] for point in box], [point[1] for point in box]
            lines.append(TextLine(text, min(xs)/scale+x0, min(ys)/scale+y0,
                                  max(xs)/scale+x0, max(ys)/scale+y0, confidence))
        return lines


class RapidOCRFullPageTextExtractor(RapidOCRTextExtractor):
    """RapidOCR detector/recognizer for unknown layouts only.

    Known templates continue using ``RapidOCRTextExtractor`` region calls;
    exposing full-page OCR as a separate type prevents accidental expansion
    of the standard-form cost envelope.
    """

    engine_name = "rapidocr_full_page"

    def __init__(self, backend=None, model_version: str = "rapidocr-onnxruntime",
                 max_full_page_side: int = 2000) -> None:
        super().__init__(backend=backend, model_version=model_version)
        self._max_full_page_side = max_full_page_side

    def extract(self, image: Image.Image) -> list[TextLine]:
        longest = max(image.size)
        scale = min(1.0, self._max_full_page_side / longest)
        working = image if scale == 1 else image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
        lines = super().extract_region(working, 0, 0, working.width, working.height)
        if scale == 1:
            return lines
        return [TextLine(line.text, line.x0 / scale, line.y0 / scale,
                         line.x1 / scale, line.y1 / scale, line.confidence)
                for line in lines]


class PaddleOCRTextExtractor:
    """Real adapter. Constructed lazily -- importing `paddleocr` at class
    definition time would make every caller of this module (including
    pure-logic unit tests) require the `[ml]` extras group installed."""

    def __init__(
        self,
        lang: str = "en",
        model_name: str = "PP-OCRv4",
        model_version: str = "paddleocr-2.x",
        cpu_threads: int = 2,
        max_full_page_side: int = 1600,
    ) -> None:
        self._lang = lang
        self._model_name = model_name
        self._model_version = model_version
        self._cpu_threads = cpu_threads
        self._max_full_page_side = max_full_page_side
        self._engine = None

    @property
    def engine_name(self) -> str:
        return "paddleocr"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ModelNotAvailableError(
                "paddleocr is not installed -- install the '[ml]' extras group "
                "(see pyproject.toml) or run inside the ML-enabled worker image"
            ) from exc
        self._engine = PaddleOCR(
            # Preparation already normalizes page orientation. Loading the
            # separate angle-classifier model duplicates work and materially
            # increases the CPU worker's cold-start memory.
            use_angle_cls=False,
            lang=self._lang,
            show_log=False,
            ocr_version=self._model_name,
            enable_mkldnn=False,
            cpu_threads=self._cpu_threads,
        )
        return self._engine

    def extract(self, image: Image.Image) -> list[TextLine]:
        # Routing needs anchor text, not full-resolution glyph geometry.
        # Bounding the longest side prevents full-page scans from creating
        # multi-gigabyte detector feature maps. Returned boxes are mapped
        # back into source-page coordinates.
        longest_side = max(image.size)
        if longest_side <= self._max_full_page_side:
            return self._run(image)
        scale = self._max_full_page_side / longest_side
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        lines = self._run(resized)
        return [
            TextLine(
                line.text,
                line.x0 / scale,
                line.y0 / scale,
                line.x1 / scale,
                line.y1 / scale,
                line.confidence,
            )
            for line in lines
        ]

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        # Regional crops are the majority of OCR calls in this pipeline and
        # are cheap to upscale individually (same cost reasoning as
        # workers.retry.alternate_preprocessing's crop-scoped presets); the
        # source scans are ~200 DPI, below the ~300 DPI most OCR engines are
        # tuned for, so a modest upscale here measurably helps small-field
        # recognition. Whole-page `extract()` deliberately stays untouched --
        # that path is cost-sensitive (tests/performance/test_throughput.py).
        # Imported lazily -- `workers.retry` imports this module too
        # (retry_service depends on TextExtractor/TextLine), so a top-level
        # import here would deadlock on the circular package init.
        from workers.retry.alternate_preprocessing import UPSCALE_FACTOR, upscale

        crop = image.crop((x0, y0, x1, y1))
        upscaled = upscale(crop, UPSCALE_FACTOR)
        lines = self._run(upscaled)
        # undo the upscale, then translate crop-local coordinates back into
        # page coordinates
        return [
            TextLine(
                l.text,
                l.x0 / UPSCALE_FACTOR + x0,
                l.y0 / UPSCALE_FACTOR + y0,
                l.x1 / UPSCALE_FACTOR + x0,
                l.y1 / UPSCALE_FACTOR + y0,
                l.confidence,
            )
            for l in lines
        ]

    def _run(self, image: Image.Image) -> list[TextLine]:
        import numpy as np

        result = self._load().ocr(np.array(image.convert("RGB")), cls=False)
        lines: list[TextLine] = []
        for page in result or []:
            for box, (text, confidence) in page or []:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                lines.append(TextLine(text, min(xs), min(ys), max(xs), max(ys), float(confidence)))
        return lines
