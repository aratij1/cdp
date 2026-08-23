"""Local integrity inspection for authorized assets; never copies assets into Git."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from packages.storage.hashing import perceptual_hash

from .contracts import CorpusAssetIntakeRecord

HASH_ALGORITHM_VERSION = "sha256+average-hash-64-v1"
_IMAGE_MIME_BY_FORMAT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "TIFF": "image/tiff",
}


def _safe_asset_path(asset_root: Path, asset_uri: str) -> Path:
    root = asset_root.resolve(strict=True)
    requested = Path(asset_uri)
    if requested.is_absolute():
        raise ValueError("ABSOLUTE_ASSET_URI_NOT_ALLOWED")
    if ".." in requested.parts:
        raise ValueError("ASSET_URI_ESCAPES_CONTROLLED_ROOT")
    candidate = (root / requested).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("ASSET_URI_ESCAPES_CONTROLLED_ROOT") from error
    candidate = candidate.resolve(strict=True)
    if not candidate.is_file():
        raise ValueError("ASSET_URI_NOT_A_FILE")
    return candidate


def _inspect_image(path: Path) -> tuple[str, int, str]:
    with Image.open(path) as image:
        detected_mime = _IMAGE_MIME_BY_FORMAT.get(str(image.format).upper())
        if detected_mime is None:
            raise ValueError("UNSUPPORTED_IMAGE_FORMAT")
        page_count = int(getattr(image, "n_frames", 1))
        image.seek(0)
        image.load()
        return detected_mime, page_count, perceptual_hash(image)


def _inspect_pdf(path: Path) -> tuple[str, int, str]:
    try:
        import fitz
    except ImportError as error:  # pragma: no cover - dependency is part of CDP runtime
        raise ValueError("PDF_INSPECTOR_UNAVAILABLE") from error
    with fitz.open(path) as document:
        if document.needs_pass:
            raise ValueError("ENCRYPTED_PDF_NOT_ALLOWED")
        if document.page_count < 1:
            raise ValueError("EMPTY_PDF")
        pixmap = document.load_page(0).get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        return "application/pdf", document.page_count, perceptual_hash(image)


def inspect_asset(record: CorpusAssetIntakeRecord, asset_root: Path) -> dict:
    """Return PHI-safe evidence: IDs/hashes/reason codes, never path or content."""
    reasons: list[str] = []
    try:
        path = _safe_asset_path(asset_root, record.asset_uri)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if data[:5] == b"%PDF":
            mime_type, page_count, observed_phash = _inspect_pdf(path)
        else:
            mime_type, page_count, observed_phash = _inspect_image(path)
        if digest != record.asset_sha256:
            reasons.append("SHA256_MISMATCH")
        if observed_phash != record.perceptual_hash:
            reasons.append("PERCEPTUAL_HASH_MISMATCH")
        if mime_type != record.mime_type:
            reasons.append("MIME_TYPE_MISMATCH")
        if page_count != record.page_count:
            reasons.append("PAGE_COUNT_MISMATCH")
    except FileNotFoundError:
        reasons.append("ASSET_NOT_FOUND")
    except (OSError, ValueError) as error:
        code = str(error)
        reasons.append(code if code.isupper() and " " not in code else "ASSET_UNREADABLE")
    return {
        "asset_id": record.asset_id,
        "integrity_passed": not reasons,
        "reason_codes": sorted(set(reasons)),
        "hash_algorithm_version": HASH_ALGORITHM_VERSION,
    }


def inspect_assets(records: tuple[CorpusAssetIntakeRecord, ...], asset_root: Path) -> dict[str, dict]:
    return {record.asset_id: inspect_asset(record, asset_root) for record in records}
