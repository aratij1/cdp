"""Integration test verifying that pending claims (from the 729 unlabelled set)
are correctly converted into LABELLED claims when cascade outputs or reviewer corrections are processed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from evaluation.schemas import GroundTruthDataset
from scripts.build_ground_truth import (
    DEFAULT_AGENT_GT_OUT,
    DEFAULT_EVAL_GT_OUT,
    DEFAULT_MANIFEST_OUT,
    build_consolidated_gt,
    save_ground_truth,
    verify_ground_truth,
)
from scripts.score_hackathon_gt_accuracy import score

ROOT = Path(__file__).resolve().parents[3]


def test_pending_claims_workflow_with_cascade_consensus():
    """Pick actual pending claims from the manifest, generate cascade OCR consensus for them,
    and verify that build_consolidated_gt converts them from PENDING to LABELLED.
    """
    manifest_path = ROOT / "evaluation_data" / "document_manifest.json"
    assert manifest_path.is_file(), "Missing manifest"
    initial_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Identify pending claims
    pending_ids = [cid for cid, info in initial_manifest.items() if info.get("status") == "PENDING"]
    assert len(pending_ids) == 729, f"Expected 729 pending claims, got {len(pending_ids)}"

    target_pending_1 = pending_ids[0]  # e.g., 'Group A__M048DJJM.001'
    target_pending_2 = pending_ids[1]  # e.g., 'Group A__M048DJJM.008'

    # Create a temporary cascade run directory with OCR candidate outputs for these pending claims
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_run = Path(tmp_dir_str) / "run_test_pending"
        claims_dir = tmp_run / "claims"
        claims_dir.mkdir(parents=True)

        # Claim 1: Multi-engine consensus on patient_name, total_charge, patient_dob
        # Two distinct engines (rapidocr + tesseract) agree -> GOLD
        claim1_dir = claims_dir / target_pending_1
        claim1_ocr_dir = claim1_dir / "ocr"
        claim1_ocr_dir.mkdir(parents=True)

        claim1_ocr_candidates = {
            "fields": [
                {
                    "field": "patient_name",
                    "candidates": [
                        {"engine": "rapidocr", "value": "SMITH, JOHN A", "raw_confidence": 0.95},
                        {"engine": "tesseract", "value": "SMITH, JOHN A", "raw_confidence": 0.92},
                    ],
                },
                {
                    "field": "total_charge",
                    "candidates": [
                        {"engine": "rapidocr", "value": "450.00", "raw_confidence": 0.96},
                        {"engine": "tesseract", "value": "450.00", "raw_confidence": 0.94},
                    ],
                },
                {
                    "field": "patient_dob",
                    "candidates": [
                        {"engine": "rapidocr", "value": "05/12/1980", "raw_confidence": 0.98},
                        {"engine": "tesseract", "value": "05/12/1980", "raw_confidence": 0.91},
                    ],
                },
            ]
        }
        (claim1_ocr_dir / "OCRCandidates.json").write_text(
            json.dumps(claim1_ocr_candidates, indent=2), encoding="utf-8"
        )
        (claim1_dir / "result.json").write_text(
            json.dumps(
                {
                    "completed": True,
                    "document": f"Group A/{target_pending_1.split('__')[1]}",
                    "fields": {
                        "patient_name": {"value": "SMITH, JOHN A", "disp": "AUTO_ACCEPTED", "reasons": ["HARD_VALIDATION_PASSED"]},
                        "total_charge": {"value": "450.00", "disp": "AUTO_ACCEPTED", "reasons": ["HARD_VALIDATION_PASSED", "LINE_TOTALS_RECONCILED"]},
                        "patient_dob": {"value": "05/12/1980", "disp": "AUTO_ACCEPTED", "reasons": ["DATE_VALID"]},
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Claim 2: Single engine high confidence -> SILVER
        claim2_dir = claims_dir / target_pending_2
        claim2_ocr_dir = claim2_dir / "ocr"
        claim2_ocr_dir.mkdir(parents=True)

        claim2_ocr_candidates = {
            "fields": [
                {
                    "field": "patient_name",
                    "candidates": [
                        {"engine": "rapidocr", "value": "DOE, JANE B", "raw_confidence": 0.97},
                    ],
                },
                {
                    "field": "total_charge",
                    "candidates": [
                        {"engine": "rapidocr", "value": "1250.00", "raw_confidence": 0.94},
                    ],
                },
            ]
        }
        (claim2_ocr_dir / "OCRCandidates.json").write_text(
            json.dumps(claim2_ocr_candidates, indent=2), encoding="utf-8"
        )
        (claim2_dir / "result.json").write_text(
            json.dumps(
                {
                    "completed": True,
                    "document": f"Group A/{target_pending_2.split('__')[1]}",
                    "fields": {
                        "patient_name": {"value": "DOE, JANE B", "disp": "AUTO_ACCEPTED", "reasons": ["HARD_VALIDATION_PASSED"]},
                        "total_charge": {"value": "1250.00", "disp": "AUTO_ACCEPTED", "reasons": ["HARD_VALIDATION_PASSED", "LINE_TOTALS_RECONCILED"]},
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Execute build_consolidated_gt with the new run directory
        agent_gt, pydantic_gt, manifest = build_consolidated_gt(run_dirs=[tmp_run])

        # VERIFICATION 1: Claims are in the merged ground truth
        assert target_pending_1 in agent_gt["claims"], f"{target_pending_1} should be in agent_gt"
        assert target_pending_2 in agent_gt["claims"], f"{target_pending_2} should be in agent_gt"

        # Check Claim 1 has GOLD labels (from consensus of rapidocr + tesseract)
        c1_fields = agent_gt["claims"][target_pending_1]["fields"]
        assert c1_fields["patient_name"]["confidence"] == "GOLD"
        assert "multi_engine_consensus" in c1_fields["patient_name"]["source"]
        assert c1_fields["total_charge"]["expected_value"] == "450.00"

        # Check Claim 2 has SILVER labels (from high-confidence single engine)
        c2_fields = agent_gt["claims"][target_pending_2]["fields"]
        assert c2_fields["patient_name"]["confidence"] in {"GOLD", "SILVER"}

        # VERIFICATION 2: Manifest status transitioned from PENDING -> LABELLED
        assert manifest[target_pending_1]["status"] == "LABELLED"
        assert manifest[target_pending_2]["status"] == "LABELLED"

        # Count of labelled claims increased, pending decreased
        new_labelled_count = sum(1 for d in manifest.values() if d["status"] == "LABELLED")
        new_pending_count = sum(1 for d in manifest.values() if d["status"] == "PENDING")
        assert new_labelled_count == 271 + 2, f"Expected 273 labelled, got {new_labelled_count}"
        assert new_pending_count == 729 - 2, f"Expected 727 pending, got {new_pending_count}"

        # VERIFICATION 3: Pydantic dataset validation succeeds
        pydantic_doc_ids = {doc.document_id for doc in pydantic_gt.documents}
        assert target_pending_1 in pydantic_doc_ids
        assert target_pending_2 in pydantic_doc_ids

        # VERIFICATION 4: Accuracy scoring against this newly built GT works
        scored_result = score(tmp_run, agent_gt)
        assert scored_result.get("claims_scored") == 2
        assert scored_result.get("field_count") == 5
        assert scored_result.get("exact_accuracy") == 1.0  # 100% exact match since results match GT!


def test_pending_claims_workflow_with_human_reviewer_feedback(monkeypatch, tmp_path):
    """Verify that when human reviewers correct an unreadable pending claim in the UI,
    it becomes a GOLD ground truth label and converts the claim from PENDING to LABELLED.
    """
    manifest_path = ROOT / "evaluation_data" / "document_manifest.json"
    initial_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pending_ids = [cid for cid, info in initial_manifest.items() if info.get("status") == "PENDING"]

    target_pending_3 = pending_ids[2]  # e.g., 'Group A__M048DJJM.011'

    # Create mock feedback corrections file
    mock_feedback_dir = tmp_path / "evaluation_results" / "feedback"
    mock_feedback_dir.mkdir(parents=True)
    mock_corrections_file = mock_feedback_dir / "corrections.jsonl"
    mock_corrections_file.write_text(
        json.dumps(
            {
                "claim_id": target_pending_3,
                "field_name": "patient_name",
                "corrected_value": "WILLIAMS, ROBERT",
                "reviewer": "qa_operator_1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Monkeypatch ROOT or the corrections path in build_ground_truth
    import scripts.build_ground_truth as bgt

    def mock_load_feedback():
        claims = {}
        for line in mock_corrections_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            cid = row["claim_id"]
            slot = claims.setdefault(cid, {"document": cid.replace("__", "/"), "fields": {}})
            slot["fields"][row["field_name"]] = {
                "expected_value": row["corrected_value"],
                "source": f"human_feedback:{row['reviewer']}",
                "confidence": "GOLD",
            }
        return claims

    monkeypatch.setattr(bgt, "load_feedback_corrections", mock_load_feedback)

    agent_gt, pydantic_gt, manifest = bgt.build_consolidated_gt()

    # Verify target_pending_3 is now in ground truth
    assert target_pending_3 in agent_gt["claims"]
    field_data = agent_gt["claims"][target_pending_3]["fields"]["patient_name"]
    assert field_data["expected_value"] == "WILLIAMS, ROBERT"
    assert field_data["confidence"] == "GOLD"
    assert "human_feedback:qa_operator_1" in field_data["source"]

    # Verify manifest status updated to LABELLED
    assert manifest[target_pending_3]["status"] == "LABELLED"
    assert manifest[target_pending_3]["field_count"] >= 1

