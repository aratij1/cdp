"""Date-cell boundaries, calendar validity and literal source semantics."""

from dataclasses import asdict, replace

import pytest

from evaluation.ub_birthdate_rule import BirthdateTopology, discover
from workers.page_detection.text_extraction import TextLine


def token(value="02292000", x=40, y=115, right=110, bottom=125):
    return TextLine(value, x, y, right, bottom, 0.9)


def run(tokens=None, **kw):
    args = {
        "form_type": "UB",
        "field_name": "patient_dob",
        "width": 1000,
        "height": 1000,
        "topology": BirthdateTopology(),
    }
    args.update(kw)
    return discover(tokens or [token()], **args)


@pytest.mark.parametrize("form", ["CMS1500", "OTHER", "UNKNOWN", "UNSTRUCTURED"])
def test_wrong_form(form):
    assert run(form_type=form) == []


def test_wrong_field():
    assert run(field_name="service_date") == []


@pytest.mark.parametrize(
    "raw", ["02302000", "02291900", "13012000", "01010000", "1C041971", "010199", "20000101"]
)
def test_no_invalid_dates_character_repair_or_century_guess(raw):
    assert run([token(raw)]) == []


def test_exact_date_and_trailing_line_artifact():
    assert run([token("02292000_")])[0]["value"] == "2000-02-29"
    assert run()[0]["review_only"]


def test_admission_and_neighbor_dates_cannot_be_borrowed():
    assert run([token(x=180, right=250)]) == []
    assert run([token(y=140, bottom=155)]) == []


def test_competing_dates_abstain():
    assert run([token("01012000"), token("02022000")]) == []


@pytest.mark.parametrize("scale", [0.5, 1, 2])
def test_scaling(scale):
    t = token()
    t = replace(t, x0=t.x0 * scale, y0=t.y0 * scale, x1=t.x1 * scale, y1=t.y1 * scale)
    assert run([t], width=int(1000 * scale), height=int(1000 * scale))[0]["value"] == "2000-02-29"


def test_no_truth_fields():
    with pytest.raises(TypeError):
        BirthdateTopology(**{**asdict(BirthdateTopology()), "reference_value": "forbidden"})
