"""OCR retry: tries alternate preprocessing presets on one failed field's
crop only, keeps whichever result improves on the original confidence."""

from PIL import Image

from workers.page_detection.text_extraction import TextLine
from workers.retry.alternate_preprocessing import (
    PRESETS, PreprocessingContext, PreprocessingRouter, apply_preset, upscale,
)
from workers.retry.retry_service import retry_field


class ConfidenceByImageSizeExtractor:
    """A fake OCR engine whose reported confidence depends on the image it
    is given -- larger (upscaled) images "read better". Lets us prove the
    retry service picks the best-performing preset without a real OCR
    engine."""

    def __init__(self, confidence_by_min_width: dict[int, float]) -> None:
        self._confidence_by_min_width = dict(
            sorted(confidence_by_min_width.items(), reverse=True)
        )

    def extract(self, image: Image.Image) -> list[TextLine]:
        for min_width, confidence in self._confidence_by_min_width.items():
            if image.width >= min_width:
                return [TextLine("some text", 0, 0, image.width, image.height, confidence)]
        return [TextLine("some text", 0, 0, image.width, image.height, 0.1)]

    def extract_region(self, image, x0, y0, x1, y1) -> list[TextLine]:
        return self.extract(image.crop((x0, y0, x1, y1)))


def _page(size=(100, 60)) -> Image.Image:
    return Image.new("L", size, color=255)


def test_retry_improves_on_low_original_confidence():
    # width 100 -> baseline (never matches any threshold) = 0.1 confidence
    # after 2x upscale, width 200 -> 0.9 confidence
    extractor = ConfidenceByImageSizeExtractor({200: 0.9})
    page = _page((100, 60))

    result = retry_field(page, region=(0, 0, 100, 60), text_extractor=extractor, original_confidence=0.3)

    assert result.improved
    assert result.confidence == 0.9
    assert result.preset_name is not None


def test_retry_does_not_improve_when_no_preset_helps():
    extractor = ConfidenceByImageSizeExtractor({})  # always returns 0.1
    page = _page((100, 60))

    result = retry_field(page, region=(0, 0, 100, 60), text_extractor=extractor, original_confidence=0.5)

    assert not result.improved
    assert result.confidence == 0.5
    assert result.preset_name is None


def test_retry_only_touches_the_requested_region():
    calls: list[tuple[int, int]] = []

    class RecordingExtractor:
        def extract(self, image: Image.Image) -> list[TextLine]:
            calls.append(image.size)
            return [TextLine("x", 0, 0, image.width, image.height, 0.99)]

        def extract_region(self, image, x0, y0, x1, y1) -> list[TextLine]:
            return self.extract(image.crop((x0, y0, x1, y1)))

    page = _page((500, 500))
    retry_field(page, region=(10, 10, 60, 40), text_extractor=RecordingExtractor(), original_confidence=0.1)

    # The bounded portfolio operates only on the field crop.
    assert 1 <= len(calls) <= 2
    assert all(w <= 60 * 2 and h <= 30 * 2 for w, h in calls)  # upscale factor is 2x


def test_preprocessing_router_uses_signals_and_never_selects_more_than_two():
    selected = PreprocessingRouter().select(PreprocessingContext(
        field_type="currency", quality_score=.2,
        failure_reason="table_grid_noise", registration_confidence=.5,
    ))
    assert selected == ("adaptive_threshold", "strong_denoise")
    assert len(selected) <= 2


def test_upscale_preset_doubles_dimensions():
    img = Image.new("L", (50, 30), color=255)
    result = upscale(img, factor=2.0)
    assert result.size == (100, 60)


def test_all_presets_run_without_error_on_a_small_crop():
    crop = Image.new("L", (40, 20), color=200)
    for _name, steps in PRESETS:
        output = apply_preset(crop, steps)
        assert output.size[0] > 0 and output.size[1] > 0
