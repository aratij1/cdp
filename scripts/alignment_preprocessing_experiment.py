"""Controlled experiment: does image preprocessing improve SIFT/RANSAC
alignment_score on the 8 documents identified as still blocked by the 0.60
registration-confidence gate after the page-selection fix?

Read-only / reporting script. Does not modify the pipeline, does not touch
any threshold, does not write to production config or crop manifests.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from packages.domain.enums import ClaimFormType
from packages.templates.registry import TemplateRegistry
from workers.page_detection.template_alignment import align_to_reference

ROOT = Path(__file__).resolve().parents[1]

DOCS = {
    "068c071d418eb7504d41d96041f5138f6454a47657c53165a66a710710720f59": ("Group B/M048JJH5.001", 3),
    "07a45c50119c63a99c6cb4582e5f3c5878ba37dc6707b0a3577e9b904bc7b83a": ("Group B/M048IJND.001", 2),
    "5952e36372a9c135273ed7902a391c3ab098dc4b48099ec5f4cbada4055e2ff3": ("Group B/M048DJJZ.001", 2),
    "f52f806fb5f917eb0b8f7438b0c8a24cbfdf5806d64366bd8523dde25e8cdf83": ("Group B/M048IJLK.001", 2),
    "40bdf29c9c7a90ae98358f06c8f75d44106b6aa6e1eb6368e6ee49314a164645": ("Group B/M048JJDJ.001", 3),
    "cec43bbe3771ade10375c4ad930466bffb4d3a3b76a6f73efee2779a37c830f0": ("Group B/M048IJMD.001", 2),
    "635372b79bd4a684a05e53aa6a91def5c11af76f87893b987d8db5c959c702b6": ("Group B/M048IJCB.001", 3),
    "a10da81afbb2c83afee4c0455a7e014f7ba835c7ce327b597fd4e2d0dde727c3": ("Group B/M048HJHK.001", 2),
}


def _pre_blur(img: np.ndarray, ksize: int) -> np.ndarray:
    return cv2.GaussianBlur(img, (ksize, ksize), 0)


def _clahe(img: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(img)


def _hist_eq(img: np.ndarray) -> np.ndarray:
    return cv2.equalizeHist(img)


def _denoise(img: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(img, h=10)


def _unsharp(img: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=3)
    return cv2.addWeighted(img, 1.5, blurred, -0.5, 0)


def _deskew(img: np.ndarray) -> np.ndarray:
    """Estimate skew via minAreaRect on thresholded ink pixels and rotate to correct it."""
    inverted = cv2.bitwise_not(img)
    _, binary = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = cv2.findNonZero(binary)
    if coords is None or len(coords) < 10:
        return img
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.1 or abs(angle) > 20:
        return img  # implausible skew estimate, leave untouched
    h, w = img.shape
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        img, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def _adaptive_threshold(img: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )


VARIANTS: dict[str, callable] = {
    "baseline": lambda img: img,
    "gaussian_blur_5": lambda img: _pre_blur(img, 5),
    "gaussian_blur_9": lambda img: _pre_blur(img, 9),
    "clahe": _clahe,
    "hist_eq": _hist_eq,
    "denoise": _denoise,
    "unsharp": _unsharp,
    "deskew": _deskew,
    "adaptive_threshold": _adaptive_threshold,
    "clahe_then_blur5": lambda img: _pre_blur(_clahe(img), 5),
    "deskew_then_clahe": lambda img: _clahe(_deskew(img)),
    "denoise_then_clahe": lambda img: _clahe(_denoise(img)),
}


def main() -> int:
    registry = TemplateRegistry.load_from_directory(ROOT / "config" / "templates")
    template = registry.latest_for_form_type(ClaimFormType.CMS1500)
    reference = registry.load_reference_image(template)
    reference_gray = np.asarray(reference.convert("L"))

    results: dict[str, dict[str, float]] = {}
    for doc_id, (file_name, verified_page) in DOCS.items():
        path = ROOT / "dataset_raw" / file_name
        with Image.open(path) as img:
            img.seek(verified_page - 1)
            source_gray = np.asarray(img.convert("L"))

        doc_results: dict[str, float] = {}
        for variant_name, fn in VARIANTS.items():
            processed = fn(source_gray.copy())
            alignment = align_to_reference(
                Image.fromarray(processed), Image.fromarray(reference_gray)
            )
            doc_results[variant_name] = round(alignment.alignment_score, 4)
            print(
                f"{doc_id[:8]} page{verified_page} {variant_name:22s} "
                f"score={alignment.alignment_score:.4f}",
                flush=True,
            )
        results[doc_id] = doc_results

    out_path = ROOT / "evaluation_results" / "alignment_preprocessing_experiment.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
