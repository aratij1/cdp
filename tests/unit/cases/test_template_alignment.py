"""OpenCV ORB feature-matching/homography alignment."""

import pytest
from PIL import Image, ImageDraw

from tests.conftest import requires_dataset
from workers.document_preparation.codecs import decode_tiff_pages
from workers.page_detection.template_alignment import RegistrationPolicy, align_to_reference


def _textured_image(
    size=(600, 800), seed_text="ABCDEFG 1234567890 XYZ QUICK BROWN FOX"
) -> Image.Image:
    """ORB needs real texture/corners -- a few lines of text plus a
    rectangle grid gives it enough keypoints to match reliably."""
    img = Image.new("L", size, color=255)
    draw = ImageDraw.Draw(img)
    for i, y in enumerate(range(20, size[1] - 20, 40)):
        draw.text((20, y), f"{seed_text} line {i}", fill=0)
    for x in range(0, size[0], 60):
        draw.line([(x, 0), (x, size[1])], fill=0, width=1)
    for y in range(0, size[1], 60):
        draw.line([(0, y), (size[0], y)], fill=0, width=1)
    return img


def test_identical_image_aligns_with_perfect_score():
    img = _textured_image()
    result = align_to_reference(img, img.copy())
    assert result.success
    assert result.alignment_score > 0.9
    assert result.homography is not None
    assert result.warped is not None
    assert result.warped.size == img.size


def test_blank_images_fail_to_align():
    blank_a = Image.new("L", (400, 400), color=255)
    blank_b = Image.new("L", (400, 400), color=255)
    result = align_to_reference(blank_a, blank_b)
    assert not result.success
    assert result.homography is None


def test_identical_page_uses_cheap_path_and_emits_evidence():
    image = _textured_image()
    result = align_to_reference(image, image.copy())
    assert result.method == "edge_phase_correlation"
    assert result.evidence is not None
    assert result.evidence.accepted
    assert result.evidence.processing_time_ms >= 0


def test_policy_can_force_sift_fallback_with_full_evidence():
    image = _textured_image()
    result = align_to_reference(image, image.copy(), RegistrationPolicy(cheap_min_confidence=1.01))
    assert result.success
    assert result.method == "sift_flann_ransac_homography"
    assert result.evidence is not None
    assert result.evidence.keypoints_source > 0
    assert result.evidence.inlier_count >= 8
    assert result.evidence.coverage_ratio is not None
    assert result.evidence.template_coverage is not None
    assert result.evidence.scale_change == pytest.approx(1.0, rel=0.02)
    assert result.evidence.rotation_degrees == pytest.approx(0.0, abs=0.5)
    assert result.evidence.perspective_distortion is not None
    assert result.evidence.corner_validity is True


def test_translated_image_still_aligns():
    base = _textured_image()
    translated = Image.new("L", base.size, color=255)
    translated.paste(base.crop((0, 0, base.width - 30, base.height - 30)), (30, 30))
    result = align_to_reference(translated, base)
    assert result.success
    assert result.good_match_count > 0


@requires_dataset
def test_real_scans_of_the_same_form_align_better_than_different_forms(dataset_raw_dir):
    """Real-data validation: two CMS-1500 scans (different claims, same
    printed form) should align to each other with a meaningfully higher
    score than a UB-04 scan aligns to a CMS-1500 reference."""

    def load(relative_path):
        data = (dataset_raw_dir / relative_path).read_bytes()
        return decode_tiff_pages(data)[0].image

    cms_reference = load("Group A/M047FJFL.001")
    cms_other = load("Group A/M047FJFL.002")
    ub_page = load("Group C/M047IJBF.001")

    same_form = align_to_reference(cms_other, cms_reference)
    cross_form = align_to_reference(ub_page, cms_reference)

    assert same_form.success
    assert same_form.alignment_score > cross_form.alignment_score
    assert same_form.good_match_count > cross_form.good_match_count
