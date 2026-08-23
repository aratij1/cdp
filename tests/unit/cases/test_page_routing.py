"""Page routing: Bundle A/B/C/D classification and CMS-1500 page selection.

Uses a fake `TextExtractor` (real OCR requires PaddleOCR, not installed on
every dev host -- see workers/page_detection/text_extraction.py) so the
*routing decision logic* is fully deterministic and testable without it.
Real-dataset tests validate the underlying OpenCV signals (grid signature,
alignment) directly in test_grid_signature.py / test_template_alignment.py.
"""

from PIL import Image, ImageDraw

from packages.domain.enums import BundleType, ClassificationMethod, PageRole
from packages.templates import TemplateRegistry
from packages.templates.registry import DEFAULT_TEMPLATE_DIR
from tests.conftest import requires_dataset
from workers.document_preparation.codecs import decode_tiff_pages
from workers.page_detection.router import PageRoutingService
from workers.page_detection.text_extraction import TextLine


class FakeTextExtractor:
    """Returns a fixed set of lines per image, keyed by `id(image)`."""

    def __init__(self) -> None:
        self._lines_by_image: dict[int, list[TextLine]] = {}
        self.extract_calls = 0

    def set_lines(self, image: Image.Image, lines: list[TextLine]) -> None:
        self._lines_by_image[id(image)] = lines

    def extract(self, image: Image.Image) -> list[TextLine]:
        self.extract_calls += 1
        return self._lines_by_image.get(id(image), [])

    def extract_region(self, image, x0, y0, x1, y1) -> list[TextLine]:
        return [
            l for l in self.extract(image) if not (l.x1 < x0 or l.x0 > x1 or l.y1 < y0 or l.y0 > y1)
        ]


def _line(text: str) -> TextLine:
    return TextLine(text=text, x0=0, y0=0, x1=200, y1=30, confidence=0.95)


def _blank_page(size=(200, 200)) -> Image.Image:
    return Image.new("L", size, color=255)


def _registry() -> TemplateRegistry:
    return TemplateRegistry.load_from_directory(DEFAULT_TEMPLATE_DIR)


def _service(extractor: FakeTextExtractor) -> PageRoutingService:
    reg = _registry()
    return PageRoutingService(
        cms_template=reg.get("cms1500", "02-12"),
        ub_template=reg.get("ub04", "2014"),
        text_extractor=extractor,
    )


def test_single_page_with_cms1500_anchors_routes_to_bundle_a():
    extractor = FakeTextExtractor()
    page = _blank_page()
    extractor.set_lines(
        page,
        [
            _line("HEALTH INSURANCE CLAIM FORM"),
            _line("APPROVED BY NATIONAL UNIFORM CLAIM COMMITTEE"),
            _line("PICA"),
        ],
    )
    result = _service(extractor).route([page])

    assert result.bundle_type == BundleType.A_CMS1500_SINGLE
    assert result.selected_page_number == 1
    assert result.template.template_id == "cms1500"
    assert result.page_roles[1] == PageRole.CMS1500_CLAIM_PAGE
    assert not result.needs_review


def test_single_page_with_ub_anchors_routes_to_bundle_c():
    extractor = FakeTextExtractor()
    page = _blank_page()
    extractor.set_lines(page, [_line("TYPE OF BILL"), _line("STATEMENT COVERS PERIOD")])
    result = _service(extractor).route([page])

    assert result.bundle_type == BundleType.C_UB_SINGLE
    assert result.selected_page_number == 1
    assert result.template.template_id == "ub04"
    assert result.page_roles[1] == PageRole.UB_CLAIM_PAGE
    assert extractor.extract_calls == 1


def test_single_page_with_no_recognizable_anchors_preserves_unknown_unstructured():
    extractor = FakeTextExtractor()
    page = _blank_page()
    extractor.set_lines(page, [_line("SOME COMPLETELY DIFFERENT DOCUMENT")])
    result = _service(extractor).route([page])

    assert result.bundle_type == BundleType.UNKNOWN_UNSTRUCTURED
    assert result.selected_page_number is None
    assert not result.needs_review


def test_multipage_bundle_selects_the_cms1500_page_and_marks_others_attachments():
    extractor = FakeTextExtractor()
    cover_letter = _blank_page()
    claim_page = _blank_page()
    attachment = _blank_page()
    extractor.set_lines(cover_letter, [_line("RE: CLAIM SUBMISSION COVER LETTER")])
    extractor.set_lines(
        claim_page,
        [
            _line("HEALTH INSURANCE CLAIM FORM"),
            _line("APPROVED BY NATIONAL UNIFORM CLAIM COMMITTEE"),
            _line("PICA"),
        ],
    )
    extractor.set_lines(attachment, [_line("MEDICAL RECORDS ATTACHMENT")])

    result = _service(extractor).route([cover_letter, claim_page, attachment])

    assert result.bundle_type == BundleType.B_CMS1500_BUNDLE
    assert result.selected_page_number == 2
    assert result.page_roles[1] == PageRole.ATTACHMENT
    assert result.page_roles[2] == PageRole.CMS1500_CLAIM_PAGE
    assert result.page_roles[3] == PageRole.ATTACHMENT
    assert not result.needs_review


def test_multipage_bundle_with_no_cms1500_signal_routes_to_bundle_d():
    extractor = FakeTextExtractor()
    pages = [_blank_page(), _blank_page(), _blank_page()]
    for p in pages:
        extractor.set_lines(p, [_line("UNRELATED CONTENT")])

    result = _service(extractor).route(pages)

    assert result.bundle_type == BundleType.D_UNSTRUCTURED
    assert result.selected_page_number is None
    assert not result.needs_review
    assert all(role == PageRole.UNSTRUCTURED_CLAIM_PAGE for role in result.page_roles.values())


def test_multipage_bundle_with_ambiguous_signal_routes_to_review():
    """Two pages each carry a *weak* partial anchor match (some, but not
    all, required phrases) with no clear winner -- this must not silently
    guess; it should escalate to human review."""
    extractor = FakeTextExtractor()
    page_a = _blank_page()
    page_b = _blank_page()
    # Both mention "PICA" (1 of 3 required anchors) but neither is a
    # confident, unique match.
    extractor.set_lines(page_a, [_line("PICA")])
    extractor.set_lines(page_b, [_line("PICA")])

    result = _service(extractor).route([page_a, page_b])

    assert result.needs_review
    assert result.selected_page_number is None


def test_no_text_extractor_configured_falls_through_to_unstructured():
    reg = _registry()
    service = PageRoutingService(
        cms_template=reg.get("cms1500", "02-12"),
        ub_template=reg.get("ub04", "2014"),
        text_extractor=None,
    )
    result = service.route([_blank_page()])
    assert result.bundle_type == BundleType.D_UNSTRUCTURED


# -- reference-image-driven escalation (grid signature / ORB alignment) ----
# These exercise the steps below anchor-phrase matching in the escalation
# ladder (docs/ARCHITECTURE.md §9), which are only reachable when an
# operator has configured a real reference image per template (see
# Template.reference_image_path) -- previously untested through
# `PageRoutingService` entirely.


def _textured_image(size=(300, 400)) -> Image.Image:
    """Same technique as test_template_alignment.py's `_textured_image` --
    ORB needs real corners/texture, not a blank page, to match reliably."""
    img = Image.new("L", size, color=255)
    draw = ImageDraw.Draw(img)
    for i, y in enumerate(range(20, size[1] - 20, 40)):
        draw.text((20, y), f"ABCDEFG 1234567890 line {i}", fill=0)
    for x in range(0, size[0], 60):
        draw.line([(x, 0), (x, size[1])], fill=0, width=1)
    for y in range(0, size[1], 60):
        draw.line([(0, y), (size[0], y)], fill=0, width=1)
    return img


def _grid_image(size=(300, 400), cell_size=40) -> Image.Image:
    """Same technique as test_grid_signature.py's `_grid_image`."""
    img = Image.new("L", size, color=255)
    draw = ImageDraw.Draw(img)
    for x in range(0, size[0], cell_size):
        draw.line([(x, 0), (x, size[1])], fill=0, width=2)
    for y in range(0, size[1], cell_size):
        draw.line([(0, y), (size[0], y)], fill=0, width=2)
    return img


def test_single_page_falls_back_to_grid_signature_against_reference_image():
    reg = _registry()
    reference = _grid_image()
    service = PageRoutingService(
        cms_template=reg.get("cms1500", "02-12"),
        ub_template=reg.get("ub04", "2014"),
        text_extractor=FakeTextExtractor(),  # no anchors scripted -- confidence 0.0
        cms_reference_image=reference,
    )

    result = service.route([reference.copy()])

    assert result.bundle_type == BundleType.A_CMS1500_SINGLE
    assert result.selected_page_number == 1
    assert result.page_scores[1].method == ClassificationMethod.GRID_LAYOUT_SIGNATURE


def test_multipage_bundle_falls_back_to_orb_alignment_against_reference_image():
    reg = _registry()
    reference = _textured_image()
    claim_page = reference.copy()
    cover_letter = _blank_page(reference.size)
    attachment = _blank_page(reference.size)
    service = PageRoutingService(
        cms_template=reg.get("cms1500", "02-12"),
        ub_template=reg.get("ub04", "2014"),
        text_extractor=FakeTextExtractor(),  # no anchors scripted for any page
        cms_reference_image=reference,
    )

    result = service.route([cover_letter, claim_page, attachment])

    assert result.bundle_type == BundleType.B_CMS1500_BUNDLE
    assert result.selected_page_number == 2
    assert result.page_scores[2].method == ClassificationMethod.TEMPLATE_SIMILARITY
    assert not result.needs_review


@requires_dataset
def test_single_page_grid_signature_thresholds_hold_against_real_dataset(dataset_raw_dir):
    """Real-data validation for GRID_CONFIDENT_THRESHOLD / GRID_AMBIGUITY_MARGIN
    (workers/page_detection/router.py): every real single-page CMS-1500 (Group
    A) and UB-04 (Group C) scan, other than the one used as each form's
    reference, must classify correctly via grid signature alone (anchor
    phrases bypassed -- they need live OCR, unavailable in this environment)
    with zero cross-form misclassification. This is what justifies lowering
    GRID_CONFIDENT_THRESHOLD from an un-tuned 0.90 to 0.75 backed by
    GRID_AMBIGUITY_MARGIN: if a future template/dataset change erodes the
    real separation margin between own-form and cross-form scores, this test
    fails instead of the router silently misrouting a live claim."""

    def load(relative_path):
        data = (dataset_raw_dir / relative_path).read_bytes()
        return decode_tiff_pages(data)[0].image

    reg = _registry()
    cms_reference = load("Group A/M047FJFL.001")
    ub_reference = load("Group C/M047IJBF.001")
    service = PageRoutingService(
        cms_template=reg.get("cms1500", "02-12"),
        ub_template=reg.get("ub04", "2014"),
        text_extractor=None,  # isolate the grid-signature escalation step
        cms_reference_image=cms_reference,
        ub_reference_image=ub_reference,
    )

    cms_files = [f"M047FJFL.{i:03d}" for i in range(2, 13)]  # .001 is the reference
    ub_files = [f"M047IJBF.{i:03d}" for i in range(2, 7)]  # .001 is the reference

    for name in cms_files:
        result = service.route_single_page(load(f"Group A/{name}"))
        assert result.bundle_type == BundleType.A_CMS1500_SINGLE, (
            f"{name}: expected CMS1500, got {result.bundle_type}"
        )

    for name in ub_files:
        result = service.route_single_page(load(f"Group C/{name}"))
        assert result.bundle_type == BundleType.C_UB_SINGLE, (
            f"{name}: expected UB04, got {result.bundle_type}"
        )
