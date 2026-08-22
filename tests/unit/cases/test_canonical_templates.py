import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from packages.domain.enums import ClaimFormType
from packages.templates.canonical import CanonicalTemplateError, load_canonical_image
from packages.templates.models import ReferenceDimensions, Template
from packages.templates.registry import TemplateRegistry


def _template() -> Template:
    return Template(
        template_id="cms1500",
        version="02-12",
        form_type=ClaimFormType.CMS1500,
        reference_dimensions=ReferenceDimensions(width_px=20, height_px=30),
        anchor_definitions=[],
        field_regions=[],
    )


def _package(root: Path) -> Path:
    package = root / "cms1500"
    package.mkdir()
    image_path = package / "canonical.png"
    Image.new("L", (20, 30), "white").save(image_path)
    for name in ("anchors.json", "fields.json"):
        (package / name).write_text("[]", encoding="utf-8")
    (package / "descriptors.npz").write_bytes(b"test-descriptors")
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    metadata = {
        "template_id": "cms1500", "form_version": "02-12",
        "source_authority": "NUCC", "source_url": "https://www.nucc.org/form.pdf",
        "source_sha256": "0" * 64, "source_page": 3,
        "provenance": "OFFICIAL_PUBLIC_BLANK", "phi_status": "NO_PHI",
        "image_sha256": digest, "width_px": 20, "height_px": 30,
        "expected_dpi": 200, "descriptor_version": "sift-v1",
        "descriptor_sha256": hashlib.sha256(b"test-descriptors").hexdigest(),
        "descriptor_keypoint_count": 50,
        "registration_algorithm_version": "sift-flann-ransac-v1",
    }
    (package / "version.json").write_text(json.dumps(metadata), encoding="utf-8")
    return package


def test_registry_loads_integrity_checked_canonical_package(tmp_path: Path) -> None:
    _package(tmp_path)
    registry = TemplateRegistry([_template()], canonical_dir=tmp_path)
    assert registry.load_reference_image(_template()).size == (20, 30)


def test_canonical_package_fails_closed_on_checksum_mismatch(tmp_path: Path) -> None:
    package = _package(tmp_path)
    Image.new("L", (20, 30), "black").save(package / "canonical.png")
    with pytest.raises(CanonicalTemplateError, match="checksum"):
        load_canonical_image(package, _template())


def test_canonical_package_rejects_phi_provenance(tmp_path: Path) -> None:
    package = _package(tmp_path)
    metadata = json.loads((package / "version.json").read_text("utf-8"))
    metadata["phi_status"] = "UNKNOWN"
    (package / "version.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(CanonicalTemplateError, match="non-PHI"):
        load_canonical_image(package, _template())
