"""Synthetic forensic checks: missing is never accepted and failures stay counted."""

import json
from copy import deepcopy

import pytest
from PIL import Image

from evaluation.governed_30_reference import ROOT, digest, load_schemas
from evaluation.governed_30_root_cause import (
    compare_rows,
    emission_complete,
    mismatch_cause,
    routing_state,
    verify_alignment,
)
from packages.claim_intelligence.normalization import comparison_key
from packages.field_policy import FieldPolicyRegistry


def completed(fields=None):
    fields = fields or []
    return {
        "fields": fields,
        "events": [
            {"topic": "extraction.completed", "envelope": {"payload": {"field_count": len(fields)}}}
        ],
        "tasks": [],
    }


def route(claim, rows=None, eligible=True):
    return routing_state(
        claim, rows or [], "patient_name", "CMS1500", FieldPolicyRegistry.load(), eligible=eligible
    )[0]


def test_absence_requires_sealed_complete_inventory():
    assert route(completed()) == "NOT_EMITTED"
    claim = completed()
    claim["events"][0]["envelope"]["payload"]["field_count"] = 1
    assert route(claim) == "UNKNOWN_BUG"
    assert route({}) == "UNKNOWN_BUG"


def test_no_automated_route_is_absent_not_accepted():
    claim = {
        "document_status": "NEEDS_REVIEW",
        "events": [
            {
                "topic": "page.selected",
                "envelope": {
                    "payload": {
                        "needs_review": True,
                        "reason_codes": ["NO_AUTOMATED_EXTRACTION_ROUTE"],
                    }
                },
            }
        ],
    }
    assert emission_complete(claim)
    assert route(claim) == "NOT_EMITTED"
    assert route(claim, eligible=False) == "NOT_ELIGIBLE"


def test_explicit_field_task_dominates_missing_or_ineligible():
    claim = completed()
    claim["tasks"] = [{"field_name": "patient_name"}]
    assert route(claim) == "HITL"
    assert route(claim, eligible=False) == "HITL"


def test_emitted_unresolved_is_not_silently_accepted():
    rows = [{"field_name": "patient_name", "disposition": "UNRESOLVED_NON_BLOCKING"}]
    assert route(completed(rows), rows) == "UNKNOWN_BUG"
    rows[0]["disposition"] = "REJECTED"
    assert route(completed(rows), rows) == "REJECTED"


def test_missing_supported_candidate_remains_failure():
    assert (
        mismatch_cause([], [], "SYNTHETIC", "patient_name", "VALID", True)[0] == "CANDIDATE_MISSING"
    )
    assert (
        mismatch_cause([], [], "SYNTHETIC", "service_date", "AMBIGUOUS_MAPPING", True)[0]
        == "TRUTH/REFERENCE_NOT_COMPARABLE"
    )


def test_matching_alternative_does_not_fix_selected_wrong_value():
    rows = [{"raw_value": "OTHER PERSON", "candidates": [{"raw_text": "EXAMPLE PERSON"}]}]
    correct, keys, expected = compare_rows("patient_name", rows, "EXAMPLE PERSON")
    assert not correct
    assert (
        mismatch_cause(rows, keys, expected, "patient_name", "VALID", True)[0] == "WRONG_CANDIDATE"
    )
    rows[0]["candidates"] = []
    assert (
        mismatch_cause(rows, keys, expected, "patient_name", "VALID", True)[0] == "EXTRACTION_WRONG"
    )


def test_conflicting_occurrences_cannot_cherry_pick():
    rows = [{"raw_value": "EXAMPLE PERSON"}, {"raw_value": "OTHER PERSON"}]
    correct, keys, expected = compare_rows("patient_name", rows, "EXAMPLE PERSON")
    assert not correct
    assert (
        mismatch_cause(rows, keys, expected, "patient_name", "VALID", True)[0]
        == "VALIDATION/SELECTION"
    )


@pytest.mark.parametrize(
    "field,left,right,agrees",
    [
        ("total_charge", "$347.89", "347.89", True),
        ("total_charge", "34789", "347.89", False),
        ("patient_dob", "02/29/2024", "2024-02-29", True),
        ("member_id", "000ABC", "ABC", False),
        ("member_id", "abc", "ABC", False),
        ("patient_name", "Example, Person", "EXAMPLE PERSON", True),
        ("patient_name", "Person Example", "EXAMPLE PERSON", False),
        ("patient_name", "PATIENT NAME EXAMPLE PERSON", "EXAMPLE PERSON", False),
        ("principal_diagnosis", "Z0000", "Z00.00", True),
    ],
)
def test_governed_comparators_do_not_invent_matches(field, left, right, agrees):
    assert (comparison_key(field, left) == comparison_key(field, right)) is agrees


@pytest.fixture
def alignment_fixture(tmp_path):
    schemas = load_schemas(ROOT, "CMS1500")
    spec = next(
        f for f in schemas["CA0"]["fields"] if f["canonical_name"] == "patient_control_number"
    )
    output = tmp_path / "synthetic.txt"
    lines = []
    for n in range(1, 31):
        line = list(" " * schemas["CA0"]["record_length"])
        line[:3] = "CA0"
        value = f"SYNTH{n:03d}"
        line[spec["start_position"] - 1 : spec["end_position"]] = value.ljust(
            spec["end_position"] - spec["start_position"] + 1
        )
        lines.extend(["".join(line), "XA0" + " " * (schemas["XA0"]["record_length"] - 3)])
    output.write_text("\n".join(lines), encoding="utf8")
    rows, manifests, references, executions, seals = [], [], [], [], {str(output): digest(output)}
    for n in range(1, 31):
        source = tmp_path / f"synthetic{n:03d}.tif"
        Image.new("L", (1, 1), n).save(source)
        h = digest(source)
        seals[str(source)] = h
        alias = f"SYNTH_{n:03d}"
        start, end = 2 * n - 1, 2 * n
        rows.append(
            {
                "claim_id": alias,
                "claim_form_type": "CMS1500",
                "actual_source_path": str(source),
                "output_text_file": output.name,
                "output_record_start": start,
                "output_record_end": end,
                "claim_record_start": "CA0",
                "claim_record_end": "XA0",
                "source_sha256": h,
                "membership_status": "EXACT",
                "source_frame_count": 1,
                "source_page_numbers": [1],
                "source_control_reference": f"SYNTH{n:03d}",
                "group": "SYNTHETIC",
                "output_claim_sequence": n,
            }
        )
        manifests.append(
            {
                "claim_alias": alias,
                "source_hash": h,
                "pages": [{}],
                "form_type": "CMS1500",
                "output_provenance": {
                    "source_file_hash": digest(output),
                    "start_line": start,
                    "end_line": end,
                },
            }
        )
        references.append({"claim_alias": alias, "form_type": "CMS1500"})
        executions.append(
            {"claim_alias": alias, "source_sha256": h, "source_frames": 1, "prepared_frames": 1}
        )
    for name, data in {
        "owner_sequence_membership.local.json": {"mappings": rows},
        "owner_sequence_input.local.json": {"sealed_inputs": seals},
        "source_owner_confirmation.json": {
            "status": "OWNER_CONFIRMED",
            "mapping_rule": "SOURCE_IMAGE_SEQUENCE_MATCHES_DATAMATICS_CLAIM_SEQUENCE",
        },
    }.items():
        (tmp_path / name).write_text(json.dumps(data))
    return tmp_path, {"claims": manifests}, {"claims": references}, {"claims": executions}


def test_thirty_claim_alignment_verified_from_control_and_sealed_source(alignment_fixture):
    result, _, _ = verify_alignment(ROOT, *alignment_fixture)
    assert result["exact"] == 30


def test_swapped_claim_sequence_is_rejected(alignment_fixture):
    frozen, *rest = alignment_fixture
    path = frozen / "owner_sequence_membership.local.json"
    data = json.loads(path.read_text())
    data["mappings"][0]["output_claim_sequence"] = 2
    data["mappings"][1]["output_claim_sequence"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="OWNER_SEQUENCE_REFERENCE_ORDER_MISMATCH"):
        verify_alignment(ROOT, frozen, *rest)


def test_cross_form_reference_pair_rejected(alignment_fixture):
    frozen, manifest, reference, execution = deepcopy(alignment_fixture)
    reference["claims"][0]["form_type"] = "UB"
    with pytest.raises(ValueError, match="CLAIM_ALIGNMENT_FAILED"):
        verify_alignment(ROOT, frozen, manifest, reference, execution)
