"""Controlled experiment: can safe preprocessing/SIFT tuning push alignment
confidence from the current ~0.60-0.78 band up to the real 0.80 E3
structural-confidence floor, without touching the 0.80 threshold itself?

Read-only / reporting script. Does not modify config, thresholds, or the
production pipeline.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from packages.domain.enums import ClaimFormType
from packages.templates.registry import TemplateRegistry
from workers.page_detection.template_alignment import (
    DEFAULT_REGISTRATION_POLICY,
    align_to_reference,
)

ROOT = Path(__file__).resolve().parents[1]
N_TRIALS = 4

# Top candidates closest to 0.80 plus a couple of already-improved mid-band docs.
DOCS = {
    "578ceb38cf4e2993a6f841478b086c980678326f459e6f84c1e986a40ec09e78": ("Group A/M048HJCX.001", 1),
    "78d258d4462bcd23a03934247019597ebd1dfce7925daa21cd8ae8e81a4e07e6": ("Group A/M048EJGE.001", 1),
    "ec06c6b4b9ed10c6734b4695c2b06823f958651a737b317d609c7126ac00bd6a": ("Group A/M048IJJT.001", 1),
    "27ff2387a69712f847eb9c09f11c011e28eeca52980d9c4b9aff3db1c2b51cc1": ("Group B/M048IJLC.001", 2),
    "eee16e60f5942b17d8aa8c29f35029749baa07a7bd3d4e88aac6c6ce95dbf685": ("Group B/M048DJKA.001", 2),
    "10aa1b42b5e8af990f3dd6f01726fa26c4fa12a3bd2ebed31ac789fa16357707": ("Group B/M048IJLQ.001", 3),
    "07a45c50119c63a99c6cb4582e5f3c5878ba37dc6707b0a3577e9b904bc7b83a": ("Group B/M048IJND.001", 2),
}


def _blur(img: np.ndarray, ksize: int) -> np.ndarray:
    return cv2.GaussianBlur(img, (ksize, ksize), 0)


def _clahe(img: np.ndarray) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(img)


def align_blurred(source: np.ndarray, reference: np.ndarray, ksize: int, policy=None):
    b_source = _blur(source, ksize) if ksize else source
    b_reference = _blur(reference, ksize) if ksize else reference
    return align_to_reference(
        Image.fromarray(b_source), Image.fromarray(b_reference), policy=policy
    )


VARIANTS = {
    "blur5": lambda s, r: align_blurred(s, r, 5),
    "blur7": lambda s, r: align_blurred(s, r, 7),
    "blur9": lambda s, r: align_blurred(s, r, 9),
    "blur11": lambda s, r: align_blurred(s, r, 11),
    "blur5_clahe": lambda s, r: align_blurred(_clahe(s), _clahe(r), 5),
    "blur5_more_features": lambda s, r: align_blurred(
        s, r, 5, policy=replace(DEFAULT_REGISTRATION_POLICY, sift_features=6000)
    ),
    "blur5_lower_lowe": lambda s, r: align_blurred(
        s, r, 5, policy=replace(DEFAULT_REGISTRATION_POLICY, lowe_ratio=0.8)
    ),
}


def main() -> int:
    registry = TemplateRegistry.load_from_directory(ROOT / "config" / "templates")
    template = registry.latest_for_form_type(ClaimFormType.CMS1500)
    reference = registry.load_reference_image(template)
    reference_gray = np.asarray(reference.convert("L"))

    results = {}
    for doc_id, (file_name, page) in DOCS.items():
        with Image.open(ROOT / "dataset_raw" / file_name) as img:
            img.seek(page - 1)
            source_gray = np.asarray(img.convert("L"))
        doc_results = {}
        for variant_name, fn in VARIANTS.items():
            scores = []
            for _ in range(N_TRIALS):
                alignment = fn(source_gray, reference_gray)
                scores.append(alignment.alignment_score)
            mean = statistics.mean(scores)
            doc_results[variant_name] = scores
            flag = "  >= 0.80 <-- CLEARS E3 FLOOR" if mean >= 0.80 else ""
            print(
                f"{doc_id[:8]} page{page} {variant_name:20s} "
                f"mean={mean:.4f} min={min(scores):.4f} max={max(scores):.4f}{flag}",
                flush=True,
            )
        results[doc_id] = doc_results

    out_path = ROOT / "evaluation_results" / "e3_threshold_experiment.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
