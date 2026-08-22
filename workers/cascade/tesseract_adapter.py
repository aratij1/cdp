"""Tesseract CLI adapter returning the platform's common TextLine shape."""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from workers.page_detection.text_extraction import TextLine


class TesseractTextExtractor:
    def __init__(
        self, psm: int = 11, language: str = "eng", whitelist: str | None = None
    ) -> None:
        self._psm = psm
        self._language = language
        self._whitelist = whitelist

    @property
    def psm(self) -> int:
        return self._psm

    @property
    def engine_name(self) -> str:
        return f"tesseract_psm_{self._psm}"

    @property
    def model_name(self) -> str:
        return f"tesseract-{self._language}"

    @property
    def model_version(self) -> str:
        return "5.x"

    def extract(self, image: Image.Image) -> list[TextLine]:
        executable = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
        if executable is None:
            windows_default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            executable = str(windows_default) if windows_default.is_file() else "tesseract"
        command = [
            executable,
            "stdin",
            "stdout",
            "-l",
            self._language,
            "--psm",
            str(self._psm),
        ]
        if self._whitelist:
            command.extend(["-c", f"tessedit_char_whitelist={self._whitelist}"])
        command.append("tsv")
        process = subprocess.run(
            command,
            input=_png_bytes(image),
            capture_output=True,
            check=True,
        )
        return parse_tsv(process.stdout.decode("utf-8", errors="replace"))

    def extract_region(
        self, image: Image.Image, x0: int, y0: int, x1: int, y1: int
    ) -> list[TextLine]:
        lines = self.extract(image.crop((x0, y0, x1, y1)))
        return [
            TextLine(
                line.text,
                line.x0 + x0,
                line.y0 + y0,
                line.x1 + x0,
                line.y1 + y0,
                line.confidence,
            )
            for line in lines
        ]


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def parse_tsv(payload: str) -> list[TextLine]:
    words: list[TextLine] = []
    for row in csv.DictReader(io.StringIO(payload), delimiter="\t"):
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf") or -1)
        except ValueError:
            continue
        if not text or confidence < 0:
            continue
        x0, y0 = float(row["left"]), float(row["top"])
        width, height = float(row["width"]), float(row["height"])
        words.append(TextLine(text, x0, y0, x0 + width, y0 + height, confidence / 100.0))
    return words


FIELD_TESSERACT_CONFIG: dict[str, tuple[int, str | None]] = {
    "date": (7, "0123456789/-"),
    "npi": (7, "0123456789"),
    "zip": (7, "0123456789-"),
    "currency": (7, "0123456789.,$-"),
    "amount": (7, "0123456789.,$-"),
    "code": (7, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"),
    "tax_id": (7, "0123456789-"),
    "checkbox": (10, None),
    "text": (7, None),
}


def for_field_type(field_type: str, language: str = "eng") -> TesseractTextExtractor:
    psm, whitelist = FIELD_TESSERACT_CONFIG.get(field_type, (7, None))
    return TesseractTextExtractor(psm=psm, language=language, whitelist=whitelist)
