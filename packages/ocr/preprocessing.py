"""Versioned, bounded field-crop preprocessing for local OCR engines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import yaml
from PIL import Image

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "ocr_preprocessing.yaml"


def _gray(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"))


def _image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(array.astype(np.uint8))


def _grayscale(image: Image.Image) -> Image.Image:
    return image.convert("L")


def _clahe(image: Image.Image) -> Image.Image:
    return _image(cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4)).apply(_gray(image)))


def _mild_contrast(image: Image.Image) -> Image.Image:
    return _image(cv2.convertScaleAbs(_gray(image), alpha=1.15, beta=0))


def _upscale_2x(image: Image.Image) -> Image.Image:
    return image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)


def _sharpen(image: Image.Image) -> Image.Image:
    source = _gray(image)
    return _image(cv2.addWeighted(source, 1.5, cv2.GaussianBlur(source, (0, 0), 1.2), -0.5, 0))


def _character_sharpen(image: Image.Image) -> Image.Image:
    source = _gray(image)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    return _image(cv2.filter2D(source, -1, kernel))


def _otsu(image: Image.Image) -> Image.Image:
    return _image(cv2.threshold(_gray(image), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])


def _edge_denoise(image: Image.Image) -> Image.Image:
    return _image(cv2.bilateralFilter(_gray(image), 5, 30, 30))


def _median_denoise(image: Image.Image) -> Image.Image:
    return _image(cv2.medianBlur(_gray(image), 3))


def _orient_field_crop(image: Image.Image) -> Image.Image:
    """Restore the expected horizontal reading direction of a field crop.

    Claim-form fields are overwhelmingly wider than they are tall.  A strongly
    portrait crop is therefore evidence of a 90/270 degree page rotation, not
    ordinary field geometry.  Keeping the gate at 1.15 avoids changing square
    checkbox and stamp crops.
    """
    if image.height > image.width * 1.15:
        return image.rotate(90, expand=True, fillcolor=255)
    return image


def _safe_border(image: Image.Image) -> Image.Image:
    """Add a small, bounded background border around edge-clipped glyphs."""
    source = _gray(image)
    padding = max(4, min(24, round(min(source.shape) * 0.12)))
    edges = np.concatenate((source[0], source[-1], source[:, 0], source[:, -1]))
    background = int(np.percentile(edges, 90))
    return _image(cv2.copyMakeBorder(
        source, padding, padding, padding, padding,
        cv2.BORDER_CONSTANT, value=background,
    ))


STEPS: dict[str, Callable[[Image.Image], Image.Image]] = {
    "orient_field_crop": _orient_field_crop, "safe_border": _safe_border,
    "grayscale": _grayscale, "clahe": _clahe, "mild_contrast": _mild_contrast,
    "upscale_2x": _upscale_2x, "sharpen": _sharpen,
    "character_sharpen": _character_sharpen, "otsu": _otsu,
    "edge_preserving_denoise": _edge_denoise, "median_denoise": _median_denoise,
}


@dataclass(frozen=True)
class AppliedPreprocessing:
    image: Image.Image
    profile: str
    version: str


class PreprocessingRegistry:
    def __init__(self, config: dict) -> None:
        self.config = config
        unknown = {step for steps in config["profiles"].values() for step in steps} - STEPS.keys()
        if unknown:
            raise ValueError(f"unknown preprocessing steps: {sorted(unknown)}")

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG) -> "PreprocessingRegistry":
        return cls(yaml.safe_load(Path(path).read_text("utf-8")))

    def resolve(self, field_name: str, field_type: str, requested: str | None = None) -> str:
        if requested:
            if requested not in self.config["profiles"]:
                raise ValueError(f"unknown preprocessing profile: {requested}")
            return requested
        searchable = f"{field_name} {field_type}".lower()
        for rule in self.config.get("field_rules", []):
            if any(token.lower() in searchable for token in rule["contains"]):
                return rule["profile"]
        return self.config["default_profile"]

    def apply(self, image: Image.Image, field_name: str, field_type: str, requested: str | None = None) -> AppliedPreprocessing:
        profile = self.resolve(field_name, field_type, requested)
        result = image
        for step in self.config["profiles"][profile]:
            result = STEPS[step](result)
        return AppliedPreprocessing(result, profile, str(self.config["version"]))
