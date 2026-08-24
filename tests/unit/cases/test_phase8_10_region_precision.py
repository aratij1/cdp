from __future__ import annotations

import pytest
from PIL import Image

from packages.field_localization import (
    FieldDefinition,
    FieldLocator,
    FieldRelationship,
    PageZone,
    RegionOwnership,
    transform_template_region,
)
from packages.page_observation import PageObservationService
from workers.page_detection.text_extraction import TextLine


class FixtureOCR:
    model_version = "fixture-v1"

    def __init__(self, lines):
        self.lines = lines

    def extract(self, _image):
        return self.lines


def _locate(datatype: str, own: str, neighbor: str):
    observation = PageObservationService(
        FixtureOCR([
            TextLine("TARGET FIELD", 100, 100, 260, 125, .99),
            TextLine(own, 100, 145, 230, 170, .98),
            TextLine(neighbor, 560, 145, 700, 170, .99),
        ]),
        preprocessing_version="fixture-v1",
    ).observe("adversarial", Image.new("RGB", (1000, 1200), "white"))
    definition = FieldDefinition(
        field_name="target", form_family="CMS1500", aliases=("TARGET FIELD",),
        page_zone=PageZone.ANY,
        relationships=(FieldRelationship(
            relationship_id="target-below-v1", relation="below",
            x0_offset=0, y0_offset=.01, x1_offset=.3, y1_offset=.08,
        ),),
        datatype=datatype, blocking=True, criticality="CRITICAL",
        definition_version="phase8.10-test",
    )
    return FieldLocator().locate(observation, definition)


@pytest.mark.parametrize(("datatype", "own", "neighbor"), [
    ("DATE", "01/02/1980", "03/04/1981"),
    ("NPI", "1234567890", "1098765432"),
    ("CURRENCY", "125.00", "999.00"),
    ("ICD_CODE", "A12.3", "B45.6"),
    ("CPT_HCPCS", "99213", "A0428"),
    ("TYPE_OF_BILL", "131", "111"),
    ("TAX_IDENTIFIER", "123456789", "987654321"),
    ("ALPHANUMERIC_ID", "AB12345", "CD98765"),
    ("PERSON_NAME", "JANE SMITH", "JOHN BROWN"),
    ("PERSON_OR_ORGANIZATION", "JANE CLINIC", "JOHN HEALTH"),
])
def test_valid_neighbor_does_not_steal_owned_region(datatype, own, neighbor):
    location = _locate(datatype, own, neighbor)
    assert location.region_ownership == RegionOwnership.REGION_OWNED
    assert location.relationship_id == "target-below-v1"
    assert location.relationship_type == "below"
    assert location.relationship_score is not None
    assert not location.wrong_crop_suspected
    assert location.candidates[0].observed_text.replace(" ", "") == own.replace(" ", "")


@pytest.mark.parametrize(("matrix", "page_size", "expected"), [
    ([[1, 0, 20], [0, 1, 30], [0, 0, 1]], None, (30, 40, 120, 70)),
    ([[2, 0, 0], [0, 2, 0], [0, 0, 1]], None, (20, 20, 200, 80)),
    ([[0, -1, 100], [1, 0, 0], [0, 0, 1]], None, (60, 10, 90, 100)),
    ([[1, 0, 0], [0, 1, 0], [0.001, 0.0005, 1]], None, (10, 9, 90, 39)),
    ([[1, 0, -50], [0, 1, -20], [0, 0, 1]], (100, 100), (0, 0, 50, 20)),
])
def test_template_region_transform_audit(matrix, page_size, expected):
    result = transform_template_region((10, 10, 100, 40), matrix, page_size)
    assert result.valid
    assert result.bbox == expected
    assert len(result.mapped_polygon) == 4


@pytest.mark.parametrize("matrix", [
    [[1, 0], [0, 1]],
    [[1, 0, 0], [0, 1, 0], [0, 0, 0]],
])
def test_invalid_template_transform_fails_closed(matrix):
    result = transform_template_region((10, 10, 100, 40), matrix)
    assert not result.valid
    assert result.bbox is None
