"""Integrity-checked canonical template packages for public blank forms."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from packages.templates.models import Template

DESCRIPTOR_VERSION = "sift-v1"
REGISTRATION_ALGORITHM_VERSION = "sift-flann-ransac-v1"
ALLOWED_PROVENANCE = {"OFFICIAL_PUBLIC_BLANK", "OPERATOR_APPROVED_NON_PHI"}


class CanonicalTemplateError(ValueError):
    """Raised when a canonical package is incomplete or fails integrity checks."""


class CanonicalTemplateMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    form_version: str
    source_authority: str
    source_url: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_page: int = Field(ge=0)
    provenance: str
    phi_status: str
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    expected_dpi: int = Field(gt=0)
    descriptor_version: str
    descriptor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    descriptor_keypoint_count: int = Field(ge=50)
    registration_algorithm_version: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_template_geometry(template: Template, package_dir: Path) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    anchors = [item.model_dump(mode="json") for item in template.anchor_definitions]
    fields: dict[str, Any] = {
        "reference_dimensions": template.reference_dimensions.model_dump(mode="json"),
        "field_regions": [item.model_dump(mode="json") for item in template.field_regions],
        "service_line_region": (
            template.service_line_region.model_dump(mode="json")
            if template.service_line_region is not None
            else None
        ),
    }
    (package_dir / "anchors.json").write_text(
        json.dumps(anchors, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (package_dir / "fields.json").write_text(
        json.dumps(fields, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_canonical_image(package_dir: Path, template: Template) -> Image.Image:
    metadata_path = package_dir / "version.json"
    image_path = package_dir / "canonical.png"
    descriptor_path = package_dir / "descriptors.npz"
    required = [
        metadata_path, image_path, descriptor_path,
        package_dir / "anchors.json", package_dir / "fields.json",
    ]
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise CanonicalTemplateError(f"incomplete canonical package: {', '.join(missing)}")

    metadata = CanonicalTemplateMetadata.model_validate_json(metadata_path.read_text("utf-8"))
    if metadata.provenance not in ALLOWED_PROVENANCE or metadata.phi_status != "NO_PHI":
        raise CanonicalTemplateError("canonical template lacks approved non-PHI provenance")
    if (metadata.template_id, metadata.form_version) != (template.template_id, template.version):
        raise CanonicalTemplateError("canonical template identity does not match registry template")
    if sha256_file(image_path) != metadata.image_sha256:
        raise CanonicalTemplateError("canonical image checksum mismatch")
    if sha256_file(descriptor_path) != metadata.descriptor_sha256:
        raise CanonicalTemplateError("canonical descriptor checksum mismatch")
    if metadata.descriptor_version != DESCRIPTOR_VERSION:
        raise CanonicalTemplateError("unsupported canonical descriptor version")
    if metadata.registration_algorithm_version != REGISTRATION_ALGORITHM_VERSION:
        raise CanonicalTemplateError("unsupported registration algorithm version")

    with Image.open(image_path) as opened:
        opened.load()
        image = opened.convert("L")
    expected = (template.reference_dimensions.width_px, template.reference_dimensions.height_px)
    if image.size != expected or image.size != (metadata.width_px, metadata.height_px):
        raise CanonicalTemplateError("canonical image dimensions do not match template geometry")
    return image
