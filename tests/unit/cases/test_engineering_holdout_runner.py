import json

from evaluation.run_engineering_holdout import _score


def test_score_joins_truth_only_after_predictions_and_counts_missing_fields(tmp_path):
    (tmp_path / "canonical_ground_truth.json").write_text(json.dumps({
        "documents": [{
            "document_id": "doc-1", "form_type": "CMS1500",
            "image_quality_bucket": "clean", "split": "holdout",
            "fields": [
                {"field_name": "patient_name", "expected_raw": "Jane Doe"},
                {"field_name": "patient_dob", "expected_raw": "2000-01-02"},
            ],
        }]
    }), "utf-8")
    report = _score([{
        "document_id": "doc-1", "route": "D_UNSTRUCTURED",
        "fields": {"patient_name": {"value": "Jane Doe"}},
        "wall_seconds": 1.0, "cpu_seconds": .25,
    }], tmp_path, limit=1)

    assert report["raw_exact_accuracy"] == .5
    assert report["raw_exact_correct"] == 1
    assert report["field_observations"] == 2
    assert report["route_counts"] == {"D_UNSTRUCTURED": 1}
    assert report["claim_stp_rate"] is None
