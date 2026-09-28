"""Unit tests for HITL self-learn (mine → memory → plan). Never auto-accept."""

from __future__ import annotations

import json
from pathlib import Path

from packages.hitl_self_learn.memory import MemoryStore, apply_events
from packages.hitl_self_learn.mine import _events_from_row, mine_run, summarize_events
from packages.hitl_self_learn.models import PatternKey, REMEDIATION_KINDS
from packages.hitl_self_learn.plan import plan_retries, write_plan
from packages.hitl_self_learn.playbook import lookup_playbook, reason_fingerprint


def test_reason_fingerprint_stable_and_discriminative():
    fp1 = reason_fingerprint(
        [
            "HARD_VALIDATION_PASSED",
            "FORMAT_VALID",
            "LINE_TOTALS_UNCORROBORATED",
            "LINE_TOTALS_GATE:SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28",
        ]
    )
    fp2 = reason_fingerprint(
        [
            "LINE_TOTALS_GATE:SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28",
            "LINE_TOTALS_UNCORROBORATED",
            "FORMAT_VALID",
        ]
    )
    assert fp1 == fp2
    assert "LINE_TOTALS_UNCORROBORATED" in fp1
    assert "SINGLE_LINE" in fp1


def test_playbook_single_line_prefers_code_fix():
    entry = lookup_playbook(
        "LINE_SUM_UNCORROBORATED",
        reason_fp="LINE_TOTALS_GATE:SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28",
    )
    assert entry.remediation == "code_fix"
    assert entry.remediation in REMEDIATION_KINDS


def test_mine_field_hitl_classifies_line_sum(tmp_path: Path):
    row = {
        "claim_id": "Group A__DEMO.001",
        "document": "Group A/DEMO.001",
        "disposition": "HITL",
        "true_stp": False,
        "review_required": True,
        "service_line_charges": 1,
        "critical_blockers": ["total_charge"],
        "fields": {
            "total_charge": {
                "disp": "HUMAN_REVIEW_REQUIRED",
                "value": "1825.00",
                "reasons": [
                    "FORMAT_VALID",
                    "LINE_TOTALS_UNCORROBORATED",
                    "LINE_TOTALS_GATE:SINGLE_LINE_DUAL_ENGINE_NEEDS_BOX28",
                ],
            }
        },
        "ts": "2026-09-26T00:00:00+00:00",
    }
    events = _events_from_row(row, run_id="unit", run_dir=None)
    assert len(events) == 1
    assert events[0].gap_class == "LINE_SUM_UNCORROBORATED"
    assert events[0].field_name == "total_charge"


def test_mine_claim_level_wrong_family():
    row = {
        "claim_id": "Group A__DEMO.002",
        "document": "Group A/DEMO.002",
        "disposition": "HITL",
        "true_stp": False,
        "claim_status": "CLAIM_REVIEW_REQUIRED",
        "fields": {
            "patient_name": {"disp": "AUTO_ACCEPTED", "value": "A B", "reasons": []},
        },
        "document_finance": {
            "gap_class": "WRONG_DOCUMENT_FAMILY",
            "reasons": ["UNKNOWN_FAMILY_NO_CMS_GEOMETRY"],
        },
    }
    events = _events_from_row(row, run_id="unit", run_dir=None)
    assert len(events) == 1
    assert events[0].gap_class == "WRONG_DOCUMENT_FAMILY"
    assert events[0].field_name == "_claim"


def test_memory_upsert_and_plan(tmp_path: Path):
    row = {
        "claim_id": "Group A__DEMO.003",
        "document": "Group A/DEMO.003",
        "disposition": "HITL",
        "true_stp": False,
        "service_line_charges": 2,
        "critical_blockers": ["total_charge"],
        "fields": {
            "total_charge": {
                "disp": "ESCALATE",
                "value": "100.00",
                "reasons": [
                    "LINE_TOTALS_UNCORROBORATED",
                    "LINE_TOTALS_GATE:MULTI_LINE_UNCORROBORATED",
                ],
            }
        },
    }
    events = _events_from_row(row, run_id="unit", run_dir=None)
    store = MemoryStore(tmp_path / "mem")
    apply_events(store, events)
    apply_events(store, events)  # second observe bumps hit_count
    patterns = store.all_patterns()
    assert len(patterns) == 1
    assert patterns[0].hit_count == 2
    assert patterns[0].remediation in REMEDIATION_KINDS

    items = plan_retries(events, store)
    assert len(items) == 1
    assert items[0].claim_id == "Group A__DEMO.003"
    assert items[0].remediation == "retry_geometry_ocr"

    paths = write_plan(items, tmp_path / "plan_out")
    assert paths["plan"].exists()
    assert paths["summary"].exists()
    summary = json.loads(paths["summary"].read_text())
    assert summary["item_count"] == 1


def test_mine_run_from_ledger(tmp_path: Path):
    run = tmp_path / "run"
    run.mkdir()
    ledger = run / "results.jsonl"
    rows = [
        {
            "claim_id": "c1",
            "document": "d1",
            "disposition": "TRUE_STP",
            "true_stp": True,
            "fields": {},
        },
        {
            "claim_id": "c2",
            "document": "d2",
            "disposition": "HITL",
            "true_stp": False,
            "service_line_charges": 0,
            "critical_blockers": ["patient_dob"],
            "fields": {
                "patient_dob": {
                    "disp": "ESCALATE",
                    "value": "1957-02-06",
                    "reasons": ["CALIBRATED_CONFIDENCE_BELOW_THRESHOLD"],
                }
            },
        },
    ]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    events = mine_run(run)
    assert len(events) == 1
    assert events[0].gap_class == "CALIBRATION_HITL"
    summary = summarize_events(events)
    assert summary["claim_count"] == 1


def test_pattern_id_stable():
    a = PatternKey("LINE_SUM_UNCORROBORATED", "total_charge", "LINE_TOTALS_UNCORROBORATED")
    b = PatternKey("LINE_SUM_UNCORROBORATED", "total_charge", "LINE_TOTALS_UNCORROBORATED")
    assert a.pattern_id() == b.pattern_id()
    assert len(a.pattern_id()) == 16


def test_record_stp_flip(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem")
    row = {
        "claim_id": "c3",
        "document": "d3",
        "disposition": "HITL",
        "true_stp": False,
        "critical_blockers": ["insured_id_number"],
        "fields": {
            "insured_id_number": {
                "disp": "HUMAN_REVIEW_REQUIRED",
                "value": "000123",
                "reasons": ["SHORT_PADDED_MEMBER_ID_NEEDS_CORROBORATION"],
            }
        },
        "service_line_charges": 0,
    }
    events = _events_from_row(row, run_id="unit", run_dir=None)
    apply_events(store, events)
    pid = store.all_patterns()[0].pattern_id
    store.record_stp_flip(pid, "c3")
    assert store.get(pid).stp_flip_count == 1
