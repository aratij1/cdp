"""Source-only, reviewed orientation diagnostic; never automatic production routing."""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image

KEYS = {
    "claim_alias",
    "page_number",
    "image_path",
    "image_sha256",
    "rotation",
    "visual_evidence",
    "authority",
    "osd_agrees",
}


def validate_rotation_job(job: dict) -> None:
    if set(job) != KEYS:
        raise ValueError("SOURCE_ONLY_ORIENTATION_SCHEMA_REQUIRED")
    if (
        job["rotation"] != 180
        or job["osd_agrees"] is not True
        or job["authority"] != "MANUALLY_VERIFIED_DIAGNOSTIC_ONLY"
        or not job["visual_evidence"]
    ):
        raise ValueError("INDEPENDENT_VISUAL_ORIENTATION_EVIDENCE_REQUIRED")
    if hashlib.sha256(Path(job["image_path"]).read_bytes()).hexdigest() != job["image_sha256"]:
        raise ValueError("SOURCE_HASH_MISMATCH")


def capture_reviewed_rotation(job: dict, primary_engine: Any) -> dict:
    validate_rotation_job(job)
    if primary_engine.engine_name != "paddleocr" or primary_engine.model_name != "PP-OCRv4":
        raise ValueError("SAME_PRIMARY_ENGINE_REQUIRED")
    started = time.perf_counter()
    with Image.open(job["image_path"]) as image:
        tokens = primary_engine.extract(image.convert("RGB").rotate(180))
    return {
        **{k: v for k, v in job.items() if k != "image_path"},
        "engine": primary_engine.engine_name,
        "model": primary_engine.model_name,
        "seconds": time.perf_counter() - started,
        "tokens": [asdict(t) for t in tokens],
    }
