"""Synthetic execution plumbing fixtures; never release truth or measured accuracy."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from evaluation.deployment_control_executor import snapshot, validate_candidate_deployment
from packages.events.topics import Topic
from packages.real_data_evaluation.blind_workflow import content_digest


def fixture(*, output=True, task=False):
    doc_id = UUID(int=1)
    now = datetime.now(UTC)
    decision = {
        "disposition": "STP_SAFE",
        "stp_eligible": True,
        "blocking_unresolved_fields": [],
        "critical_blockers": [],
        "contradictions": [],
    }
    latest = NS(
        topic=Topic.CLAIM_VALIDATED.value,
        outbox_id=UUID(int=3),
        created_at=now,
        envelope={"event_id": str(UUID(int=3)), "payload": {"claim_decision": decision}},
    )
    events = [latest]
    if output:
        events.append(
            NS(
                topic=Topic.OUTPUT_COMPLETED.value,
                created_at=now,
                outbox_id=uuid5(NAMESPACE_URL, "cdp:output:" + latest.envelope["event_id"]),
                envelope={
                    "event_id": str(UUID(int=4)),
                    "payload": {"document_id": str(doc_id), "claim_decision": decision},
                },
            )
        )
    row = NS(
        field_id=UUID(int=2),
        service_line_number=None,
        page_number=1,
        field_name="member_id",
        disposition="AUTO_ACCEPTED",
        validation_status="VALID",
        raw_value="SYNTHETIC",
        normalized_value="SYNTHETIC",
        is_critical=True,
        validation_reasons=[],
        reference_evidence=None,
    )
    tasks = []
    if task:
        tasks.append(
            NS(
                field_id=row.field_id,
                correction_corrected_at=None,
                claimed_at=None,
                assigned_to=None,
                status="OPEN",
                review_reason_codes=["SYNTHETIC_REVIEW"],
            )
        )
    data = [[NS(page_number=1, page_id=UUID(int=5))], [row], tasks, events]

    class Session:
        def get(self, *args):
            return NS(
                sha256="ingested",
                status="OUTPUT_GENERATED" if output else "VALIDATED",
                claim_id=None,
            )

        def scalars(self, query):
            return NS(all=lambda: data.pop(0))

    cohort = {
        "claims": {
            "claim-synthetic": {
                "package_id": "pkg-synthetic",
                "page_ids": ["page-synthetic"],
                "expected_field_keys": [["page-synthetic", "member_id"]],
            }
        }
    }
    mapping = {
        "claim-synthetic": {
            "document_id": str(doc_id),
            "ingested_sha256": "ingested",
            "source_pages": [
                {"page_id": "page-synthetic", "rendered_page_sha256": "synthetic-hash"}
            ],
        }
    }
    return Session(), cohort, mapping, data, {"pipeline_configuration_sha256": "synthetic"}


def capture(parts, final=False):
    session, cohort, mapping, _, config = parts
    return snapshot(session, cohort, mapping, final=final, configuration=config)


def test_safe_decision_waits_for_output_completion():
    assert capture(fixture(output=False)) is None


def test_stp_records_explicit_completion_and_binding():
    result = capture(fixture())
    claim = result["claims"]["claim-synthetic"]
    assert claim["output_completed"] and claim["automatic_output_safely_generated"]
    assert claim["required_fields_pass"] and claim["required_evidence_pass"]
    assert claim["human_reviewed"] is False
    field = result["fields"][0]
    assert field["claim_id"] == "claim-synthetic"
    assert field["source_sha256"] == "synthetic-hash"
    assert field["package_id"] == "pkg-synthetic"
    assert result["execution_provenance"][0]["output_event_ids"]


def test_review_task_excludes_automatic_accept_and_stp():
    result = capture(fixture(task=True))
    assert result["fields"][0]["accepted"] is False
    assert result["fields"][0]["review_required"] is True
    assert result["claims"]["claim-synthetic"]["automatic_output_safely_generated"] is False
    assert result["claims"]["claim-synthetic"]["human_intervention_required"] is True


def test_claimed_task_forbids_raw_capture_before_value_correction():
    parts = fixture(task=True)
    parts[3][2][0].claimed_at = datetime.now(UTC)
    with pytest.raises(ValueError, match="RAW_CAPTURE_AFTER_HUMAN_INTERVENTION"):
        capture(parts)


def test_human_confirmed_field_forbids_raw_capture_without_review_task():
    parts = fixture()
    parts[3][1][0].disposition = "HUMAN_CONFIRMED"
    with pytest.raises(ValueError, match="RAW_CAPTURE_AFTER_HUMAN_INTERVENTION"):
        capture(parts)


def test_newer_unrelated_output_does_not_prove_completion():
    parts = fixture()
    parts[3][3][1].outbox_id = UUID(int=8)
    assert capture(parts) is None
    parts = fixture()
    parts[3][3][1].outbox_id = UUID(int=8)
    assert capture(parts, final=True) is None


def test_invalid_page_number_is_not_negative_index_binding():
    parts = fixture()
    parts[3][1][0].page_number = 0
    with pytest.raises(ValueError, match="CANONICAL_FIELD_PAGE_OUT_OF_RANGE"):
        capture(parts)


def test_source_order_must_match_governed_membership():
    parts = fixture()
    parts[2]["claim-synthetic"]["source_pages"][0]["page_id"] = "another-page"
    with pytest.raises(ValueError, match="SOURCE_PAGE_ORDER_BINDING"):
        capture(parts)


def test_frozen_candidate_requires_matching_governed_deployment_attestation(tmp_path):
    sha = "a" * 40
    (tmp_path / "candidate_freeze.local.json").write_text(json.dumps({"candidate_commit_sha": sha}))
    settings = {
        "candidate_commit_sha": sha,
        "deployment_id": "synthetic-deployment",
        "pipeline_configuration_sha256": "synthetic-config",
    }
    with pytest.raises(ValueError, match="ATTESTATION_REQUIRED"):
        validate_candidate_deployment(settings, tmp_path)
    attestation = {**settings, "governed": True, "approval_reference": "synthetic-test-only"}
    (tmp_path / "deployment_attestation.local.json").write_text(json.dumps(attestation))
    settings["deployment_attestation_sha256"] = content_digest(attestation)
    validate_candidate_deployment(settings, tmp_path)
    settings["candidate_commit_sha"] = "b" * 40
    with pytest.raises(ValueError, match="SHA_MISMATCH"):
        validate_candidate_deployment(settings, tmp_path)


def test_runtime_standard_output_captures_evidence_without_claiming_safe():
    parts = fixture()
    for event in parts[3][3]:
        event.envelope["payload"]["claim_decision"].update(
            disposition="STP_STANDARD", runtime_evidence_safe=True, stp_safe=False)
    result = capture(parts)
    claim = result["claims"]["claim-synthetic"]
    assert claim["decision"] == "STP_STANDARD"
    assert claim["automatic_output_safely_generated"] and claim["semantic_authority_pass"]


def test_output_hold_is_captured_as_claim_review_without_waiting_forever():
    parts = fixture()
    latest, output = parts[3][3]
    latest.envelope["payload"]["claim_decision"]["disposition"] = "STP_STANDARD"
    output.topic = Topic.OUTPUT_REVIEW_REQUIRED.value
    output.envelope["payload"]["reason_codes"] = ["OWNER_APPROVED_COMPLETE_MEMBERSHIP_REQUIRED"]
    result = capture(parts)
    claim = result["claims"]["claim-synthetic"]
    assert claim["decision"] == "CLAIM_REVIEW_REQUIRED"
    assert not claim["automatic_output_safely_generated"] and not claim["semantic_authority_pass"]
