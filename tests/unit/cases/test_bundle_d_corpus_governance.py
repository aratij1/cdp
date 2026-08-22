import json

import pytest
from PIL import Image

from evaluation.freeze_bundle_d_corpus import freeze


def _corpus(tmp_path, duplicate: bool):
    (tmp_path / "manifest.json").write_text(json.dumps({
        "dataset_id": "test", "frozen_holdout": True, "tuning_prohibited": True,
    }), "utf-8")
    rows = []
    for index in range(2):
        path = tmp_path / f"{index}.png"
        Image.new("L", (10, 10), 255 if duplicate or index == 0 else 0).save(path)
        rows.append({"document_id": str(index), "path": path.name})
    (tmp_path / "ground_truth.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), "utf-8"
    )


def test_freeze_rejects_byte_identical_documents(tmp_path):
    _corpus(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="byte-identical"):
        freeze(tmp_path)
    assert json.loads((tmp_path / "freeze_audit.json").read_text("utf-8"))["status"] == "REJECTED_DUPLICATES"


def test_freeze_records_unique_content_hashes(tmp_path):
    _corpus(tmp_path, duplicate=False)
    audit = freeze(tmp_path)
    assert audit["status"] == "FROZEN"
    assert audit["duplicate_document_count"] == 0
