"""Build a deterministic, non-PHI canonical package from an approved blank PDF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

from packages.templates.canonical import (
    DESCRIPTOR_VERSION,
    REGISTRATION_ALGORITHM_VERSION,
    export_template_geometry,
    sha256_file,
)
from packages.templates.registry import TemplateRegistry


def build(args: argparse.Namespace) -> None:
    registry = TemplateRegistry.load_from_directory(args.template_dir)
    template = registry.get(args.template_id, args.version)
    output = args.output_dir / template.template_id
    output.mkdir(parents=True, exist_ok=True)

    document = pymupdf.open(args.source)
    if args.page >= document.page_count:
        raise ValueError(f"page {args.page} is outside {document.page_count}-page PDF")
    pixmap = document.load_page(args.page).get_pixmap(dpi=args.dpi, alpha=False)
    rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    target = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, target, interpolation=cv2.INTER_AREA)
    Image.fromarray(gray).save(output / "canonical.png", optimize=True)

    sift = cv2.SIFT_create()
    keypoints, descriptors = sift.detectAndCompute(gray, None)
    if descriptors is None or len(keypoints) < 50:
        raise ValueError("canonical form has insufficient SIFT features")
    points = np.asarray([point.pt for point in keypoints], dtype=np.float32)
    np.savez_compressed(output / "descriptors.npz", keypoints=points, descriptors=descriptors)
    export_template_geometry(template, output)

    metadata = {
        "template_id": template.template_id,
        "form_version": template.version,
        "source_authority": args.source_authority,
        "source_url": args.source_url,
        "source_sha256": sha256_file(args.source),
        "source_page": args.page,
        "provenance": "OFFICIAL_PUBLIC_BLANK",
        "phi_status": "NO_PHI",
        "image_sha256": sha256_file(output / "canonical.png"),
        "width_px": target[0],
        "height_px": target[1],
        "expected_dpi": args.dpi,
        "descriptor_version": DESCRIPTOR_VERSION,
        "descriptor_sha256": sha256_file(output / "descriptors.npz"),
        "descriptor_keypoint_count": len(keypoints),
        "registration_algorithm_version": REGISTRATION_ALGORITHM_VERSION,
    }
    (output / "version.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(output), "features": len(keypoints), **metadata}, indent=2))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--source", type=Path, required=True)
    result.add_argument("--source-url", required=True)
    result.add_argument("--source-authority", required=True)
    result.add_argument("--page", type=int, required=True)
    result.add_argument("--dpi", type=int, default=200)
    result.add_argument("--template-id", required=True)
    result.add_argument("--version", required=True)
    result.add_argument("--template-dir", type=Path, default=Path("config/templates"))
    result.add_argument("--output-dir", type=Path, default=Path("templates"))
    return result


if __name__ == "__main__":
    build(parser().parse_args())
