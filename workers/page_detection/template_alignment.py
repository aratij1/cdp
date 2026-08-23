"""Adaptive registration: cheap edge alignment, then SIFT/FLANN/RANSAC."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees, sqrt
from time import perf_counter

import cv2
import numpy as np
from PIL import Image

from packages.domain.registration import RegistrationEvidence
from workers.page_detection.template_compatibility import (
    TemplateCompatibilityEvidence,
    TemplateCompatibilityStatus,
    assess_template_compatibility,
)


@dataclass(frozen=True)
class RegistrationPolicy:
    lowe_ratio: float = 0.72
    ransac_reprojection_threshold: float = 4.0
    min_good_matches: int = 12
    min_inliers: int = 8
    # Variable claim text creates many legitimate Lowe-filtered outliers.
    # This floor is therefore paired with inlier-count, reprojection and
    # page-coverage gates; the ratio is never an acceptance signal alone.
    min_inlier_ratio: float = 0.12
    max_reprojection_error: float = 5.0
    min_coverage_ratio: float = 0.12
    cheap_min_confidence: float = 0.92
    cheap_max_aspect_delta: float = 0.015
    sift_features: int = 3000
    min_scale: float = 0.65
    max_scale: float = 1.55
    max_abs_rotation_degrees: float = 8.0
    # Dimensionless projective edge displacement after normalizing H[2,2].
    # Ordinary scanner keystone stays below ~0.02; degenerate homographies
    # observed on wrong-form matches are orders of magnitude larger.
    max_perspective_distortion: float = 0.02


DEFAULT_REGISTRATION_POLICY = RegistrationPolicy()


@dataclass(frozen=True)
class AlignmentResult:
    success: bool
    alignment_score: float
    good_match_count: int
    homography: np.ndarray | None
    warped: Image.Image | None
    method: str
    inlier_ratio: float = 0.0
    reprojection_error: float | None = None
    accepted: bool = False
    evidence: RegistrationEvidence | None = None
    compatibility: TemplateCompatibilityEvidence | None = None
    cheap_evidence: RegistrationEvidence | None = None
    sift_attempted: bool = False


def _gray(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.uint8)


def _failure(method: str, reason: str, elapsed_ms: float = 0.0, **values) -> AlignmentResult:
    evidence = RegistrationEvidence(
        algorithm=method,
        accepted=False,
        rejection_reason=reason,
        processing_time_ms=elapsed_ms,
        **values,
    )
    return AlignmentResult(
        False,
        0.0,
        evidence.good_matches,
        None,
        None,
        method,
        evidence.inlier_ratio,
        evidence.reprojection_error,
        False,
        evidence,
    )


def _cheap_alignment(
    candidate: np.ndarray, reference: np.ndarray, policy: RegistrationPolicy
) -> AlignmentResult:
    started = perf_counter()
    ch, cw = candidate.shape
    rh, rw = reference.shape
    aspect_delta = abs((cw / ch) - (rw / rh)) / (rw / rh)
    if aspect_delta > policy.cheap_max_aspect_delta:
        return _failure(
            "edge_phase_correlation", "aspect_ratio_mismatch", (perf_counter() - started) * 1000
        )
    resized = cv2.resize(candidate, (rw, rh), interpolation=cv2.INTER_AREA)
    cand_edges = cv2.Canny(resized, 60, 180).astype(np.float32)
    ref_edges = cv2.Canny(reference, 60, 180).astype(np.float32)
    if np.count_nonzero(cand_edges) < 50 or np.count_nonzero(ref_edges) < 50:
        return _failure(
            "edge_phase_correlation",
            "insufficient_edge_structure",
            (perf_counter() - started) * 1000,
        )
    (dx, dy), response = cv2.phaseCorrelate(cand_edges, ref_edges)
    confidence = float(np.clip(response, 0.0, 1.0))
    if confidence < policy.cheap_min_confidence:
        return _failure(
            "edge_phase_correlation",
            "cheap_confidence_below_threshold",
            (perf_counter() - started) * 1000,
            alignment_confidence=confidence,
        )
    matrix = np.array([[rw / cw, 0.0, dx], [0.0, rh / ch, dy], [0.0, 0.0, 1.0]])
    warped = cv2.warpPerspective(candidate, matrix, (rw, rh), borderValue=255)
    evidence = RegistrationEvidence(
        algorithm="edge_phase_correlation",
        alignment_confidence=confidence,
        coverage_ratio=1.0,
        template_coverage=1.0,
        scale_change=sqrt(abs(np.linalg.det(matrix[:2, :2]))),
        rotation_degrees=0.0,
        perspective_distortion=0.0,
        corner_validity=True,
        transform_matrix=matrix.tolist(),
        accepted=True,
        processing_time_ms=(perf_counter() - started) * 1000,
    )
    return AlignmentResult(
        True,
        confidence,
        0,
        matrix,
        Image.fromarray(warped),
        evidence.algorithm,
        accepted=True,
        evidence=evidence,
    )


def _sift_alignment(
    candidate: np.ndarray, reference: np.ndarray, policy: RegistrationPolicy
) -> AlignmentResult:
    started = perf_counter()
    sift = cv2.SIFT_create(nfeatures=policy.sift_features)
    kp_source, desc_source = sift.detectAndCompute(candidate, None)
    kp_template, desc_template = sift.detectAndCompute(reference, None)
    common = {
        "keypoints_source": len(kp_source),
        "keypoints_template": len(kp_template),
    }
    if desc_source is None or desc_template is None or len(kp_source) < 4:
        return _failure(
            "sift_flann_ransac_homography",
            "insufficient_keypoints",
            (perf_counter() - started) * 1000,
            **common,
        )
    matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    pairs = matcher.knnMatch(desc_source, desc_template, k=2)
    good = [
        pair[0]
        for pair in pairs
        if len(pair) == 2 and pair[0].distance < policy.lowe_ratio * pair[1].distance
    ]
    common.update(candidate_match_count=len(pairs), good_matches=len(good))
    if len(good) < policy.min_good_matches:
        return _failure(
            "sift_flann_ransac_homography",
            "insufficient_good_matches",
            (perf_counter() - started) * 1000,
            **common,
        )
    src = np.float32([kp_source[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_template[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, policy.ransac_reprojection_threshold)
    if matrix is None or mask is None:
        return _failure(
            "sift_flann_ransac_homography",
            "homography_not_found",
            (perf_counter() - started) * 1000,
            **common,
        )
    inliers = mask.ravel().astype(bool)
    inlier_count = int(inliers.sum())
    inlier_ratio = inlier_count / len(good)
    projected = cv2.perspectiveTransform(src, matrix)
    errors = np.linalg.norm(projected[inliers] - dst[inliers], axis=2).ravel()
    reprojection_error = float(errors.mean()) if errors.size else None
    source_hull = cv2.convexHull(src[inliers]) if inlier_count >= 3 else None
    template_hull = cv2.convexHull(dst[inliers]) if inlier_count >= 3 else None
    source_coverage = (
        float(cv2.contourArea(source_hull)) / (candidate.shape[0] * candidate.shape[1])
        if source_hull is not None
        else 0.0
    )
    template_coverage = (
        float(cv2.contourArea(template_hull)) / (reference.shape[0] * reference.shape[1])
        if template_hull is not None
        else 0.0
    )
    coverage = min(source_coverage, template_coverage)
    normalized = matrix / matrix[2, 2]
    scale_change = sqrt(abs(float(np.linalg.det(normalized[:2, :2]))))
    rotation_degrees = degrees(atan2(float(normalized[1, 0]), float(normalized[0, 0])))
    perspective_distortion = float(
        np.linalg.norm(normalized[2, :2]) * max(candidate.shape[0], candidate.shape[1])
    )
    source_corners = np.float32(
        [[[0, 0]], [[candidate.shape[1] - 1, 0]], [[candidate.shape[1] - 1, candidate.shape[0] - 1]], [[0, candidate.shape[0] - 1]]]
    )
    transformed_corners = cv2.perspectiveTransform(source_corners, matrix).reshape(-1, 2)
    margin_x, margin_y = reference.shape[1] * 0.1, reference.shape[0] * 0.1
    corner_validity = bool(
        np.isfinite(transformed_corners).all()
        and cv2.isContourConvex(transformed_corners.astype(np.float32))
        and np.all(transformed_corners[:, 0] >= -margin_x)
        and np.all(transformed_corners[:, 0] <= reference.shape[1] + margin_x)
        and np.all(transformed_corners[:, 1] >= -margin_y)
        and np.all(transformed_corners[:, 1] <= reference.shape[0] + margin_y)
    )
    confidence = float(
        np.clip(
            0.65 * inlier_ratio
            + 0.25 * min(1.0, coverage / 0.35)
            + 0.10 * max(0.0, 1.0 - (reprojection_error or 99.0) / policy.max_reprojection_error),
            0.0,
            1.0,
        )
    )
    reasons: list[str] = []
    if inlier_count < policy.min_inliers:
        reasons.append("insufficient_inliers")
    if inlier_ratio < policy.min_inlier_ratio:
        reasons.append("low_inlier_ratio")
    if reprojection_error is None or reprojection_error > policy.max_reprojection_error:
        reasons.append("high_reprojection_error")
    if coverage < policy.min_coverage_ratio:
        reasons.append("low_coverage")
    if not policy.min_scale <= scale_change <= policy.max_scale:
        reasons.append("unsafe_scale_change")
    if abs(rotation_degrees) > policy.max_abs_rotation_degrees:
        reasons.append("unsafe_rotation")
    if perspective_distortion > policy.max_perspective_distortion:
        reasons.append("unsafe_perspective_distortion")
    if not corner_validity:
        reasons.append("invalid_transformed_corners")
    accepted = not reasons
    evidence = RegistrationEvidence(
        algorithm="sift_flann_ransac_homography",
        **common,
        inlier_count=inlier_count,
        inlier_ratio=inlier_ratio,
        reprojection_error=reprojection_error,
        coverage_ratio=coverage,
        template_coverage=template_coverage,
        scale_change=scale_change,
        rotation_degrees=rotation_degrees,
        perspective_distortion=perspective_distortion,
        corner_validity=corner_validity,
        homography_quality=confidence,
        alignment_confidence=confidence,
        transform_matrix=matrix.tolist(),
        accepted=accepted,
        rejection_reason=",".join(reasons) or None,
        processing_time_ms=(perf_counter() - started) * 1000,
    )
    warped = cv2.warpPerspective(
        candidate, matrix, (reference.shape[1], reference.shape[0]), borderValue=255
    )
    return AlignmentResult(
        accepted,
        confidence,
        len(good),
        matrix,
        Image.fromarray(warped),
        evidence.algorithm,
        inlier_ratio,
        reprojection_error,
        accepted,
        evidence,
    )


def align_to_reference(
    candidate: Image.Image,
    reference: Image.Image,
    policy: RegistrationPolicy | None = None,
    *,
    family: str | None = None,
    enforce_compatibility_precheck: bool = False,
) -> AlignmentResult:
    selected = policy or DEFAULT_REGISTRATION_POLICY
    candidate_arr, reference_arr = _gray(candidate), _gray(reference)
    cheap = _cheap_alignment(candidate_arr, reference_arr, selected)
    if cheap.success:
        return AlignmentResult(
            **{**cheap.__dict__, "cheap_evidence": cheap.evidence}
        )
    compatibility = assess_template_compatibility(candidate, reference, family=family)
    if (
        enforce_compatibility_precheck
        and compatibility.status == TemplateCompatibilityStatus.INCOMPATIBLE
    ):
        rejected = _failure(
            "template_compatibility_precheck",
            "template_lineage_mismatch",
        )
        return AlignmentResult(
            **{
                **rejected.__dict__,
                "compatibility": compatibility,
                "cheap_evidence": cheap.evidence,
                "sift_attempted": False,
            }
        )
    sift = _sift_alignment(candidate_arr, reference_arr, selected)
    return AlignmentResult(
        **{
            **sift.__dict__,
            "compatibility": compatibility,
            "cheap_evidence": cheap.evidence,
            "sift_attempted": True,
        }
    )
