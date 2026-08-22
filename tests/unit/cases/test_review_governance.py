from pathlib import Path

import pytest

from packages.criticality import CriticalityLevel
from packages.review_governance import (
    TrustedLabelExporter,
    TrustedLabelRequest,
    evaluate_trusted_label,
)


def request(**changes):
    values = {
        "task_id": "t1",
        "tenant_id": "tenant",
        "document_id": "d1",
        "document_family": "CMS1500",
        "field_name": "npi",
        "criticality": CriticalityLevel.C3,
        "crop_reference": "s3://bucket/crop.png",
        "crop_sha256": "a" * 64,
        "previous_value": "123",
        "corrected_value": "456",
        "reviewer": "alice",
        "approver": "bob",
        "validator": "validator",
        "correction_reason": "verified visible digits",
        "deterministic_validation_passed": True,
        "claim_revalidated": True,
        "evidence_visible": True,
        "crop_quality_approved": True,
        "source_policy_version": "hitl-v1",
    }
    values.update(changes)
    return TrustedLabelRequest(**values)


def test_same_reviewer_cannot_approve_training_label():
    result = evaluate_trusted_label(request(approver="alice"))
    assert not result.eligible
    assert "INDEPENDENT_APPROVER_REQUIRED" in result.reason_codes


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"deterministic_validation_passed": False}, "DETERMINISTIC_VALIDATION_REQUIRED"),
        ({"claim_revalidated": False}, "CLAIM_REVALIDATION_REQUIRED"),
        ({"evidence_visible": False}, "VISIBLE_CROP_EVIDENCE_REQUIRED"),
        ({"crop_quality_approved": False}, "CROP_QUALITY_NOT_APPROVED"),
    ],
)
def test_untrusted_or_low_quality_labels_are_ineligible(change, reason):
    assert reason in evaluate_trusted_label(request(**change)).reason_codes


def test_export_is_append_only_hash_chained_and_tamper_detectable(tmp_path: Path):
    exporter = TrustedLabelExporter(tmp_path / "trusted.jsonl")
    exporter.append(request())
    exporter.append(request(task_id="t2", document_id="d2"))
    assert exporter.verify_chain()
    content = exporter.path.read_text(encoding="utf-8")
    exporter.path.write_text(
        content.replace("verified visible digits", "tampered", 1), encoding="utf-8"
    )
    assert not exporter.verify_chain()


def test_ineligible_label_is_never_written(tmp_path: Path):
    exporter = TrustedLabelExporter(tmp_path / "trusted.jsonl")
    with pytest.raises(ValueError, match="not trusted"):
        exporter.append(request(approver="alice"))
    assert not exporter.path.exists()
