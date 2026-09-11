"""Repeated-trial version of the preprocessing experiment: SIFT/RANSAC's
findHomography has real run-to-run variance (confirmed: std ~0.05 on
identical input), so a single-shot alignment_score comparison is not
reliable. This script runs N repetitions per (document, variant) pair and
reports the mean and range, for both the 8 blocked documents and a control
group of documents that are not currently blocked -- to check whether any
preprocessing choice that helps the blocked set would also regress
documents that already work.

Read-only / reporting script. Does not modify the pipeline or any config.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from packages.domain.enums import ClaimFormType
from packages.templates.registry import TemplateRegistry
from workers.page_detection.template_alignment import align_to_reference

ROOT = Path(__file__).resolve().parents[1]
N_TRIALS = 5

TARGET_DOCS = {
    "068c071d418eb7504d41d96041f5138f6454a47657c53165a66a710710720f59": ("Group B/M048JJH5.001", 3),
    "07a45c50119c63a99c6cb4582e5f3c5878ba37dc6707b0a3577e9b904bc7b83a": ("Group B/M048IJND.001", 2),
    "5952e36372a9c135273ed7902a391c3ab098dc4b48099ec5f4cbada4055e2ff3": ("Group B/M048DJJZ.001", 2),
    "f52f806fb5f917eb0b8f7438b0c8a24cbfdf5806d64366bd8523dde25e8cdf83": ("Group B/M048IJLK.001", 2),
    "40bdf29c9c7a90ae98358f06c8f75d44106b6aa6e1eb6368e6ee49314a164645": ("Group B/M048JJDJ.001", 3),
    "cec43bbe3771ade10375c4ad930466bffb4d3a3b76a6f73efee2779a37c830f0": ("Group B/M048IJMD.001", 2),
    "635372b79bd4a684a05e53aa6a91def5c11af76f87893b987d8db5c959c702b6": ("Group B/M048IJCB.001", 3),
    "a10da81afbb2c83afee4c0455a7e014f7ba835c7ce327b597fd4e2d0dde727c3": ("Group B/M048HJHK.001", 2),
}

# A handful of Group A single-page documents already known to work well,
# used to check for regressions from any preprocessing candidate.
CONTROL_DOCS = {
    "7df8d08e5a0436b2f1262591cb2b6543797518fba8fdec6c471b5a7409f19646": ("Group A/M048HJHO.001", 1),
    "2cb1bad8dc2ba6b069ff46be762c89d3892240181c2a7bac88d01e2cd3ebbc09": ("Group A/M048JJH1.001", 1),
    "fd4cfe3ee44d9a31752ef2fa05799fb923e946fe9ef211f6e703eef57aecfea2": ("Group A/M048IJDP.001", 1),
    "0ec6faf55825f4de63fc96c8b24371a46234ef6230f5846f25d55ec1eb17e99f": ("Group A/M048IJPD.001", 1),
}


def _pre_blur(img: np.ndarray, ksize: int) -> np.ndarray:
    return cv2.GaussianBlur(img, (ksize, ksize), 0)


def _clahe(img: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(img)


VARIANTS = {
    "baseline": lambda img: img,
    "gaussian_blur_5": lambda img: _pre_blur(img, 5),
    "gaussian_blur_9": lambda img: _pre_blur(img, 9),
    "clahe_then_blur5": lambda img: _pre_blur(_clahe(img), 5),
}


def main() -> int:
    registry = TemplateRegistry.load_from_directory(ROOT / "config" / "templates")
    template = registry.latest_for_form_type(ClaimFormType.CMS1500)
    reference = registry.load_reference_image(template)
    reference_gray = np.asarray(reference.convert("L"))

    def score_group(docs: dict, label: str) -> dict:
        results: dict[str, dict[str, list[float]]] = {}
        for doc_id, (file_name, page) in docs.items():
            with Image.open(ROOT / "dataset_raw" / file_name) as img:
                img.seek(page - 1)
                source_gray = np.asarray(img.convert("L"))
            doc_results: dict[str, list[float]] = {}
            for variant_name, fn in VARIANTS.items():
                processed = fn(source_gray.copy())
                trial_scores = []
                for _ in range(N_TRIALS):
                    alignment = align_to_reference(
                        Image.fromarray(processed), Image.fromarray(reference_gray)
                    )
                    trial_scores.append(alignment.alignment_score)
                doc_results[variant_name] = trial_scores
                mean = statistics.mean(trial_scores)
                print(
                    f"[{label}] {doc_id[:8]} page{page} {variant_name:20s} "
                    f"mean={mean:.4f} min={min(trial_scores):.4f} max={max(trial_scores):.4f}",
                    flush=True,
                )
            results[doc_id] = doc_results
        return results

    target_results = score_group(TARGET_DOCS, "TARGET")
    control_results = score_group(CONTROL_DOCS, "CONTROL")

    out = {"target": target_results, "control": control_results, "n_trials": N_TRIALS}
    out_path = ROOT / "evaluation_results" / "alignment_preprocessing_experiment2.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
