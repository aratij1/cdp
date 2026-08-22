from evaluation.raw_error_analysis import classify_error, pareto


def _row(**updates):
    row = {
        "document_family": "CMS1500", "field_name": "patient_name", "correct": False,
        "expected": "JANE SMITH", "raw_value": "JANE SM1TH", "label_contaminants": [],
        "foreground_ratio": .1, "condition": "clean_scan", "registration_accepted": True,
        "other_truth": {}, "criticality": "C2", "blocking": True,
    }
    row.update(updates)
    return row


def test_classifier_separates_synthetic_label_overlap_from_ocr_error():
    category, crop, _, confidence = classify_error(_row(label_contaminants=["insured_name"]))
    assert (category, crop, confidence) == ("SYNTHETIC_RENDERING_ARTIFACT", "CROP_MULTI_FIELD", 1.0)
    category, crop, _, _ = classify_error(_row())
    assert (category, crop) == ("OCR_CHARACTER_ERROR", "CROP_CORRECT_TEXT_VISIBLE")


def test_classifier_detects_wrong_neighbor_and_registration_failure():
    assert classify_error(_row(raw_value="ABC123", other_truth={"member_id": "ABC123"}))[0] == "WRONG_ROI"
    assert classify_error(_row(condition="rotation", registration_accepted=False))[0] == "REGISTRATION_FAILURE"


def test_pareto_sorts_by_error_contribution_and_tracks_cumulative_percentage():
    rows = [
        _row(field_name="a"), _row(field_name="a"), _row(field_name="b"),
        _row(field_name="b", correct=True),
    ]
    result = pareto(rows)
    assert [item["field_name"] for item in result] == ["a", "b"]
    assert result[0]["error_contribution"] == 2 / 3
    assert result[-1]["cumulative_error_percentage"] == 1.0
