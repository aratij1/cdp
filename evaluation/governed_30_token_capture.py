"""Reference-free capture helpers for the isolated candidate coverage experiment.

Run in an environment with the selected OCR adapter installed. Inputs contain
only hashed source locations and label-derived geometry; eligibility is decided
in the separate evaluation layer. Nothing here emits an accepted runtime field.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image

from workers.field_candidates.name_interpretations import interpret_complete_name

SOURCE_KEYS = {"claim_alias", "page_number", "image_path", "image_sha256"}
REGION_KEYS = SOURCE_KEYS | {"field", "bbox", "name_convention", "handwriting_confirmed"}


def validate_input(job: dict, *, region: bool) -> None:
    allowed = REGION_KEYS if region else SOURCE_KEYS
    if set(job) != allowed:
        raise ValueError("SOURCE_ONLY_INPUT_SCHEMA_REQUIRED")
    if region and (
        len(job["bbox"]) != 4
        or job["bbox"][0] >= job["bbox"][2]
        or job["bbox"][1] >= job["bbox"][3]
    ):
        raise ValueError("NONEMPTY_REGION_REQUIRED")
    if hashlib.sha256(Path(job["image_path"]).read_bytes()).hexdigest() != job["image_sha256"]:
        raise ValueError("SOURCE_HASH_MISMATCH")


def capture_primary(job: dict, engine: Any) -> dict:
    validate_input(job, region=False)
    started = time.perf_counter()
    with Image.open(job["image_path"]) as image:
        tokens = engine.extract(image.convert("RGB"))
    return {
        **{k: v for k, v in job.items() if k != "image_path"},
        "engine": engine.engine_name,
        "model": engine.model_name,
        "model_version": engine.model_version,
        "max_full_page_side": 1600,
        "scope": "NEW_PRIMARY_ENGINE_CAPTURE_NOT_ORIGINAL_RUN_TOKENS",
        "latency_seconds": time.perf_counter() - started,
        "tokens": [asdict(t) for t in tokens],
    }


def capture_region(job: dict, engine: Any, *, mode: str) -> dict:
    validate_input(job, region=True)
    if mode not in {"rapid", "rapid_clahe", "paddle"}:
        raise ValueError("BOUNDED_PRINTED_REGION_MODE_REQUIRED")
    import psutil  # type: ignore[import-untyped]

    with Image.open(job["image_path"]) as image:
        x0, y0, x1, y1 = job["bbox"]
        box = (
            max(0, int(x0) - 4),
            max(0, int(y0) - 4),
            min(image.width, int(x1) + 5),
            min(image.height, int(y1) + 5),
        )
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("REGION_OUTSIDE_SOURCE")
        crop = image.convert("RGB").crop(box)
    if mode == "rapid_clahe":
        import cv2
        import numpy as np

        gray = cv2.cvtColor(np.array(crop), cv2.COLOR_RGB2GRAY)
        crop = Image.fromarray(
            cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
        ).convert("RGB")
    started = time.perf_counter()
    before = psutil.Process().memory_info().rss
    lines = engine.extract_region(crop, 0, 0, crop.width, crop.height)
    raw = " ".join(t.text for t in sorted(lines, key=lambda t: (t.y0, t.x0)))
    values = [raw]
    if job["field"] in {"patient_name", "insured_name"} and (
        job["name_convention"] == "LAST_FIRST" or raw.count(",") == 1
    ):
        values = [
            " ".join(x for x in [n.first, n.middle, n.last, n.suffix] if x)
            for n in interpret_complete_name(raw, "LAST_FIRST")
            if n.convention == "LAST_FIRST"
        ] + values
    return {
        **{k: v for k, v in job.items() if k != "image_path"},
        "engine": engine.engine_name,
        "mode": mode,
        "raw_value": raw,
        "values": values,
        "seconds": time.perf_counter() - started,
        "rss_delta_bytes": psutil.Process().memory_info().rss - before,
        "rss_after_bytes": psutil.Process().memory_info().rss,
        "region_bbox": box,
        "review_only": True,
    }


def write_exclusive(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf8") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
