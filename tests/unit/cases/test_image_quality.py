from PIL import Image, ImageDraw, ImageFilter

from packages.image_quality import assess_image_quality


def _page() -> Image.Image:
    image = Image.new("L", (850, 1170), 255)
    draw = ImageDraw.Draw(image)
    for y in range(80, 1050, 45):
        draw.text((70, y), "HEALTH CLAIM 1234567890", fill=0)
        draw.line((60, y + 20, 790, y + 20), fill=80)
    return image


def test_quality_contract_is_bounded_and_records_dimensions():
    result = assess_image_quality(_page())
    assert result.width_px == 850
    assert result.height_px == 1170
    assert 0 <= result.quality_score <= 1
    assert 0 <= result.text_density <= 1
    assert result.assessment_version == "iq-v1"


def test_blurred_page_has_lower_blur_score():
    sharp = _page()
    blurred = sharp.filter(ImageFilter.GaussianBlur(radius=4))
    assert assess_image_quality(blurred).blur_score < assess_image_quality(sharp).blur_score


def test_blank_low_resolution_page_reports_quality_reasons():
    result = assess_image_quality(Image.new("L", (85, 117), 255))
    assert "LOW_RESOLUTION" in result.reason_codes
    assert "BLUR_DETECTED" in result.reason_codes
