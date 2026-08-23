import json

import pytest
from pydantic import ValidationError

from evaluation.build_tuning_truth_sample import SEED, build
from evaluation.manage_tuning_truth import freeze
from evaluation.tuning_truth.contracts import NormalizedBBox


def test_tuning_truth_sample_is_deterministic_and_split_safe(tmp_path):
    first = build(tmp_path / "first", SEED)
    second = build(tmp_path / "second", SEED)

    assert first["selection_sha256"] == second["selection_sha256"]
    assert first["page_count"] == 250
    assert first["family_distribution"] == {
        "CMS1500": 110,
        "CUSTOM_INSTITUTIONAL": 3,
        "CUSTOM_PROFESSIONAL": 27,
        "UB04": 110,
    }
    assert first["observation_only_pages_selected"] == 0
    assert {row["tuning_status"] for row in first["records"]} == {"TUNING_PERMITTED"}


def test_generated_truth_streams_are_empty_until_human_verification(tmp_path):
    output = tmp_path / "result"
    build(output)

    assert (output / "field_truth.jsonl").read_text() == ""
    assert (output / "crop_truth.jsonl").read_text() == ""
    assert (output / "ub_service_line_truth.jsonl").read_text() == ""
    state = json.loads((output / "dataset_freeze.json").read_text())
    assert state["frozen"] is False
    assert state["status"] == "BLOCKED_PENDING_HUMAN_VERIFICATION"


def test_freeze_fails_closed_while_annotation_tasks_are_incomplete(tmp_path):
    results = tmp_path / "result"
    build(results)

    with pytest.raises(ValueError, match="annotation tasks remain incomplete"):
        freeze(results, tmp_path / "dataset")


def test_normalized_bbox_must_be_inside_page_and_have_positive_area():
    with pytest.raises(ValidationError):
        NormalizedBBox(x1=0.5, y1=0.2, x2=0.4, y2=0.3)
    with pytest.raises(ValidationError):
        NormalizedBBox(x1=-0.1, y1=0.2, x2=0.4, y2=0.3)
