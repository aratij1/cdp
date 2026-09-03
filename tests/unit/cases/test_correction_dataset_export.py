import json

import pytest

from packages.retraining import JsonlCorrectionSink, correction_example, export_correction_dataset


def test_export_is_source_disjoint_and_training_only(tmp_path):
    source = tmp_path / "corrections.jsonl"
    sink = JsonlCorrectionSink(source)
    for index in range(60):
        group = f"source-{index // 2}"
        sink.append(correction_example(
            f"doc-{index}", "patient_name", "JANE D0E", "JANE DOE", None, "reviewer-a",
            source_group_id=group, model_provenance={"ocr": "rapidocr-v1"},
        ))

    output = tmp_path / "weekly"
    manifest = export_correction_dataset(source, output, seed="locked-seed")
    assert sum(manifest.record_counts.values()) == 60
    split_groups = {}
    for split in ("train", "calibration", "holdout"):
        rows = [json.loads(line) for line in (output / f"{split}.jsonl").read_text().splitlines()]
        split_groups[split] = {row["source_group_id"] for row in rows}
        assert all(row["usage_authority"] == "TRAINING_ONLY" for row in rows)
        assert all(row["runtime_acceptance_authority"] is False for row in rows)
    assert split_groups["train"].isdisjoint(split_groups["calibration"])
    assert split_groups["train"].isdisjoint(split_groups["holdout"])
    assert split_groups["calibration"].isdisjoint(split_groups["holdout"])


def test_export_rejects_any_raw_correction_claiming_runtime_authority(tmp_path):
    source = tmp_path / "corrections.jsonl"
    source.write_text(json.dumps({
        "document_id": "d1", "field_name": "npi", "corrected_value": "123",
        "runtime_acceptance_authority": True,
    }) + "\n")
    with pytest.raises(ValueError, match="improperly claims runtime authority"):
        export_correction_dataset(source, tmp_path / "out")
