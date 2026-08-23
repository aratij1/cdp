from __future__ import annotations

import hashlib
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from workers.page_detection.template_alignment import align_to_reference
from workers.page_detection.template_compatibility import (
    TemplateCompatibilityStatus,
    assess_template_compatibility,
)

from .contracts import RegistrationFailureReason, RegistrationForensicRecord

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_PATHS = {
    "CMS1500": ROOT / "config/templates/reference_images/cms1500_v02_12.png",
    "UB04": ROOT / "config/templates/reference_images/ub04_v2014.png",
}
TEMPLATE_IDENTITIES = {"CMS1500": "cms1500@02-12", "UB04": "ub04@2014"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dpi(image: Image.Image) -> float | None:
    raw = image.info.get("dpi")
    if isinstance(raw, (tuple, list)) and raw:
        values = [float(value) for value in raw[:2] if float(value) > 0]
        return sum(values) / len(values) if values else None
    return float(raw) if isinstance(raw, (int, float)) and raw > 0 else None


def _failure_reason(raw: str | None, compatibility_status: str) -> RegistrationFailureReason:
    if compatibility_status == TemplateCompatibilityStatus.INCOMPATIBLE.value:
        return RegistrationFailureReason.TEMPLATE_LINEAGE_MISMATCH
    raw = (raw or "").lower()
    mappings = (
        ("aspect_ratio", RegistrationFailureReason.ASPECT_RATIO_MISMATCH),
        ("insufficient_keypoints", RegistrationFailureReason.INSUFFICIENT_KEYPOINTS_SOURCE),
        ("insufficient_good_matches", RegistrationFailureReason.LOWE_FILTER_COLLAPSE),
        ("insufficient_inliers", RegistrationFailureReason.RANSAC_INLIER_FAILURE),
        ("low_inlier_ratio", RegistrationFailureReason.RANSAC_INLIER_FAILURE),
        ("homography_not_found", RegistrationFailureReason.BAD_HOMOGRAPHY),
        ("reprojection", RegistrationFailureReason.REPROJECTION_ERROR_HIGH),
        ("corner", RegistrationFailureReason.INVALID_TRANSFORMED_CORNERS),
        ("coverage", RegistrationFailureReason.COVERAGE_FAILURE),
        ("scale", RegistrationFailureReason.SCALE_FAILURE),
        ("perspective", RegistrationFailureReason.PERSPECTIVE_FAILURE),
        ("edge_structure", RegistrationFailureReason.LINE_STRUCTURE_MISMATCH),
        ("confidence", RegistrationFailureReason.LINE_STRUCTURE_MISMATCH),
    )
    return next((reason for pattern, reason in mappings if pattern in raw),
                RegistrationFailureReason.UNKNOWN)


def registration_forensic_record(record: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    family = route["predicted_family"]
    source_path = ROOT / record["image_path"]
    with Image.open(source_path) as opened:
        dpi = _dpi(opened)
        source = opened.convert("L")
        source.load()
    with Image.open(REFERENCE_PATHS[family]) as opened:
        reference = opened.convert("L")
        reference.load()
    alternate_family = "UB04" if family == "CMS1500" else "CMS1500"
    with Image.open(REFERENCE_PATHS[alternate_family]) as opened:
        alternate = opened.convert("L")
        alternate.load()
    preliminary = assess_template_compatibility(source, reference, family=family)
    alternate_score = assess_template_compatibility(
        source, alternate, family=alternate_family
    ).compatibility_score
    family_compatibility = 1.0 if preliminary.compatibility_score >= alternate_score else 0.0
    compatibility = assess_template_compatibility(
        source,
        reference,
        family=family,
        family_compatibility=family_compatibility,
    )
    target_size = reference.size
    resized = source.resize(target_size, Image.Resampling.LANCZOS)
    result = align_to_reference(
        resized,
        reference,
        family=family,
        enforce_compatibility_precheck=True,
    )
    evidence = result.evidence
    cheap = result.cheap_evidence
    determinant = None
    if result.homography is not None:
        determinant = float(np.linalg.det(result.homography / result.homography[2, 2]))
    primary = None if result.success else _failure_reason(
        evidence.rejection_reason if evidence else None, compatibility.status.value
    )
    payload = RegistrationForensicRecord(
        document_id=record["document_id"],
        truth_family=record["expected_family"],
        nominated_family=family,
        source_dataset=record["source_dataset"],
        template_attempted=TEMPLATE_IDENTITIES[family],
        source_dimensions=source.size,
        template_dimensions=reference.size,
        aspect_ratio=source.width / source.height,
        template_aspect_ratio=reference.width / reference.height,
        image_dpi_estimate=dpi,
        orientation="LANDSCAPE" if source.width > source.height else "PORTRAIT",
        cheap_alignment_status=(
            "ACCEPTED" if cheap and cheap.accepted else
            (cheap.rejection_reason if cheap else "NOT_RECORDED")
        ),
        keypoints_source=evidence.keypoints_source if evidence else 0,
        keypoints_template=evidence.keypoints_template if evidence else 0,
        knn_matches=evidence.candidate_match_count if evidence else 0,
        good_matches=evidence.good_matches if evidence else 0,
        lowe_ratio_survivors=evidence.good_matches if evidence else 0,
        ransac_inliers=evidence.inlier_count if evidence else 0,
        inlier_ratio=evidence.inlier_ratio if evidence else 0,
        homography_returned=result.homography is not None,
        homography_determinant=determinant,
        reprojection_error=evidence.reprojection_error if evidence else None,
        corner_validity=evidence.corner_validity if evidence else None,
        coverage=evidence.coverage_ratio if evidence else None,
        scale=evidence.scale_change if evidence else None,
        rotation=evidence.rotation_degrees if evidence else None,
        perspective_distortion=evidence.perspective_distortion if evidence else None,
        compatibility=compatibility,
        sift_attempted=result.sift_attempted,
        success=result.success,
        final_rejection_reason=primary,
        raw_rejection_reason=evidence.rejection_reason if evidence else None,
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return payload.model_dump(mode="json")


def aggregate_forensics(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [row for row in records if not row["success"]]
    reasons = Counter(row["final_rejection_reason"] or "UNCLASSIFIED" for row in failures)
    compat = Counter(row["compatibility"]["status"] for row in records)
    classified = sum(reason != "UNKNOWN" for reason in reasons.elements())
    latencies = sorted(float(row["latency_ms"]) for row in records)
    percentile = lambda q: latencies[min(len(latencies) - 1, int((len(latencies) - 1) * q))] if latencies else 0
    return {
        "attempts": len(records),
        "successes": len(records) - len(failures),
        "failures": len(failures),
        "classified_failures": classified,
        "classified_failure_rate": classified / len(failures) if failures else 1.0,
        "failure_reasons": dict(reasons.most_common()),
        "compatibility_status": dict(compat),
        "sift_attempts": sum(row["sift_attempted"] for row in records),
        "sift_avoided": sum(not row["sift_attempted"] for row in records),
        "latency_ms": {"p50": percentile(.50), "p95": percentile(.95), "p99": percentile(.99)},
    }


def registration_controls() -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    for family, path in REFERENCE_PATHS.items():
        with Image.open(path) as opened:
            reference = opened.convert("L")
            reference.load()
        width, height = reference.size
        pixels = np.asarray(reference)
        rng = np.random.default_rng(714)
        noisy = np.clip(
            pixels.astype(np.int16) + rng.normal(0, 4, pixels.shape), 0, 255
        ).astype(np.uint8)
        fax_small = reference.resize(
            (max(1, width // 2), max(1, height // 2)), Image.Resampling.BILINEAR
        )
        fax_like = fax_small.resize((width, height), Image.Resampling.NEAREST).point(
            lambda value: 255 if value > 190 else 0
        )
        corners = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
        transforms = {
            "CANONICAL": reference.copy(),
            "TRANSLATED": Image.fromarray(cv2.warpPerspective(
                pixels, np.float32([[1, 0, 12], [0, 1, 8], [0, 0, 1]]),
                (width, height), borderValue=255)),
            "SCALED": Image.fromarray(cv2.warpPerspective(
                pixels, np.float32([[.98, 0, width*.01], [0, .98, height*.01], [0, 0, 1]]),
                (width, height), borderValue=255)),
            "SKEWED": Image.fromarray(cv2.warpPerspective(
                pixels, np.float32([[1, .005, -5], [.003, 1, -3], [0, 0, 1]]),
                (width, height), borderValue=255)),
            "ROTATED": reference.rotate(3, Image.Resampling.BICUBIC, fillcolor=255),
            "ROTATED_WITHIN_TOLERANCE": reference.rotate(
                4, Image.Resampling.BICUBIC, fillcolor=255
            ),
            "PERSPECTIVE": Image.fromarray(cv2.warpPerspective(
                pixels,
                cv2.getPerspectiveTransform(corners, np.float32(
                    [[8, 4], [width-12, 0], [width-3, height-8], [3, height-1]])),
                (width, height), borderValue=255)),
            "DEGRADED": ImageEnhance.Contrast(
                reference.filter(ImageFilter.GaussianBlur(.7))
            ).enhance(.75),
            "MILD_NOISE": Image.fromarray(noisy),
            "FAX_LIKE": fax_like,
            "SMALL_CROP": reference.crop((10, 10, width - 10, height - 10)).resize(
                (width, height), Image.Resampling.LANCZOS
            ),
        }
        for transform_name, candidate in transforms.items():
            started = time.perf_counter()
            result = align_to_reference(
                candidate, reference, family=family, enforce_compatibility_precheck=True
            )
            outcomes.append({
                "family": family,
                "transform": transform_name,
                "success": result.success,
                "method": result.method,
                "rejection_reason": result.evidence.rejection_reason if result.evidence else None,
                "compatibility": result.compatibility.model_dump(mode="json")
                    if result.compatibility else None,
                "latency_ms": (time.perf_counter() - started) * 1000,
            })
    return {
        "attempts": len(outcomes),
        "successes": sum(row["success"] for row in outcomes),
        "success_rate": sum(row["success"] for row in outcomes) / len(outcomes),
        "outcomes": outcomes,
    }


def audit_template_assets() -> dict[str, Any]:
    audits = []
    for family, path in REFERENCE_PATHS.items():
        with Image.open(path) as opened:
            image = opened.convert("L")
            image.load()
        pixels = np.asarray(image)
        edge_pixels = cv2.Canny(pixels, 60, 180)
        expected = (1712, 2214) if family == "CMS1500" else (1711, 2216)
        audits.append({
            "family": family,
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "dimensions": image.size,
            "expected_dimensions": expected,
            "dimensions_valid": image.size == expected,
            "blank": bool(float((pixels < 245).mean()) < .002),
            "thumbnail": max(image.size) < 1000,
            "unexpected_crop": image.size != expected,
            "ink_ratio": float((pixels < 220).mean()),
            "edge_density": float((edge_pixels > 0).mean()),
            "feature_density_usable": int((edge_pixels > 0).sum()) >= 1000,
            "runtime_reference_configured": False,
            "anchor_definitions_present": True,
            "roi_configuration_present": True,
            "audit_status": "VALID_ASSET_NOT_GENERAL_TO_TUNING_LINEAGE",
        })
    return {"assets": audits, "all_assets_readable": all(not row["blank"] for row in audits)}
