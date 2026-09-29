"""Unit tests for Ground Truth integrity, schema conformance, and coverage."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.schemas import GroundTruthDataset
from packages.evaluation.agent_gt_score import exact_match
from scripts.score_hackathon_gt_accuracy import (
    CRITICAL,
    _canon_date,
    _canon_id,
    _canon_money,
    _canon_name,
)

ROOT = Path(__file__).resolve().parents[3]
AGENT_GT_PATH = ROOT / "evaluation_data" / "hackathon_agent_gt" / "field_truth.json"
EVAL_GT_PATH = ROOT / "evaluation_data" / "ground_truth.json"
MANIFEST_PATH = ROOT / "evaluation_data" / "document_manifest.json"


def test_agent_ground_truth_exists_and_valid():
    assert AGENT_GT_PATH.is_file(), f"Missing agent GT file at {AGENT_GT_PATH}"
    payload = json.loads(AGENT_GT_PATH.read_text(encoding="utf-8"))
    assert payload.get("dataset") == "Hackathon - 1000 Claims.zip"
    claims = payload.get("claims", {})
    assert len(claims) >= 200, f"Expected at least 200 claims, got {len(claims)}"

    stats = payload.get("stats", {})
    assert stats.get("field_labels", 0) >= 800

    # Ensure critical fields have valid expected_values and confidence
    for cid, cdata in list(claims.items())[:20]:
        assert "document" in cdata
        fields = cdata.get("fields", {})
        assert len(fields) > 0
        for fname, fmeta in fields.items():
            assert "expected_value" in fmeta
            assert fmeta.get("confidence") in {"GOLD", "SILVER"}


def test_pydantic_evaluation_ground_truth_valid():
    assert EVAL_GT_PATH.is_file(), f"Missing evaluation GT file at {EVAL_GT_PATH}"
    dataset = GroundTruthDataset.model_validate_json(EVAL_GT_PATH.read_text(encoding="utf-8"))
    assert len(dataset.documents) >= 200
    for doc in dataset.documents[:20]:
        assert doc.document_id
        assert doc.file_name
        assert doc.form_type in {"CMS1500", "UB04", "UNSTRUCTURED"}
        assert doc.split in {"calibration", "validation", "holdout"}
        assert len(doc.fields) > 0


def test_manifest_covers_all_raw_documents():
    assert MANIFEST_PATH.is_file(), f"Missing manifest at {MANIFEST_PATH}"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert len(manifest) == 1000, f"Expected 1000 claims in manifest, found {len(manifest)}"
    labelled = [d for d in manifest.values() if d.get("status") == "LABELLED"]
    pending = [d for d in manifest.values() if d.get("status") == "PENDING"]
    assert len(labelled) >= 200
    assert len(pending) > 0


def test_canon_functions_behavior():
    assert _canon_date("07/16/1946") == "1946-07-16"
    assert _canon_id("0000374350") == "374350"
    assert _canon_id("W1234567") == "W1234567"
    assert _canon_money("$ 1,160.00") == "1160.00"
    assert _canon_name("THOMAS, DARLENE M.") == "THOMASDARLENEM"
