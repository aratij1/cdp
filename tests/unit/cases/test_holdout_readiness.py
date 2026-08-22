import json

from evaluation.holdout_readiness import build_readiness_record


def test_missing_external_holdout_is_recorded_without_fabricating_assets(tmp_path):
    manifest = tmp_path / "evaluation" / "holdout" / "manifest.json"
    readiness = tmp_path / "results" / "holdout_readiness.json"

    record = build_readiness_record(
        manifest_path=manifest, readiness_path=readiness,
    )

    assert record["dataset_id"] == "PRODUCTION_HOLDOUT_V1"
    assert record["status"] == "NEEDS_MORE_DATA"
    assert record["freeze_status"] == "NOT_FROZEN"
    assert record["eligible_for_evaluation"] is False
    assert record["assets"] == []
    assert "NO_INDEPENDENT_EXTERNAL_SOURCE" in record["eligibility_reasons"]
    assert json.loads(manifest.read_text("utf-8")) == record
    assert json.loads(readiness.read_text("utf-8")) == record
