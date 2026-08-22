"""Canonical prepared-image boundary for routing evaluation and diagnostics."""

from __future__ import annotations

from PIL import Image

from workers.document_preparation.preprocessing import (
    apply_orientation, denoise, deskew, detect_orientation, detect_skew_angle,
)

ROUTING_INPUT_PIPELINE_VERSION="routing-input-v4.0"


def prepare_routing_image(image:Image.Image)->Image.Image:
    working=image.convert("L")
    working=apply_orientation(working,detect_orientation(working))
    working=deskew(working,detect_skew_angle(working))
    return denoise(working)
