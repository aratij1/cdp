import json

import pytest

from packages.shadow_evaluation import AppendOnlyShadowClaimSink, ClaimShadowObservation


def observation(index: int, **changes) -> ClaimShadowObservation:
    values = {
        "claim_id": f"claim-{index}",
        "source_group_id": "hospital-a",
        "source_segment": "CMS1500_SCANNER_A",
        "production_requires_review": True,
        "shadow_requires_review": False,
        "evaluated_field_decisions": 5,
        "correct_field_decisions": 5,
        "evaluated_critical_field_decisions": 3,
        "correct_critical_field_decisions": 3,
        "accepted_field_decisions": 5,
        "accepted_critical_field_decisions": 3,
        "correct_accepted_field_decisions": 5,
        "correct_accepted_critical_field_decisions": 3,
        "false_accepts": 0,
        "critical_false_accepts": 0,
        "wrong_crops": 1,
        "wrong_crops_detected": 1,
        "runtime_latency_ms": 100,
        "cost_usd": .01,
        "runtime_decision_parity": True,
        "route_governance_passed": True,
    }
    values.update(changes)
    return ClaimShadowObservation(**values)


def test_capture_deidentifies_ids_and_verifies_hash_chain(tmp_path):
    ledger = tmp_path / "shadow.jsonl"
    sink = AppendOnlyShadowClaimSink(ledger, identity_key=b"test-secret")
    sink.append(observation(1))
    sink.append(observation(2))
    assert sink.verify()
    text = ledger.read_text(encoding="utf-8")
    assert "claim-1" not in text
    assert "hospital-a" not in text
    assert len(sink.observations()) == 2
    assert all(row.shadow_only for row in sink.observations())


def test_duplicate_claim_is_rejected(tmp_path):
    sink = AppendOnlyShadowClaimSink(tmp_path / "shadow.jsonl", identity_key=b"secret")
    sink.append(observation(1))
    with pytest.raises(ValueError, match="duplicate"):
        sink.append(observation(1))


def test_capture_rejects_serving_authority(tmp_path):
    sink = AppendOnlyShadowClaimSink(tmp_path / "shadow.jsonl", identity_key=b"secret")
    with pytest.raises(ValueError, match="non-authoritative"):
        sink.append(observation(1, shadow_only=False))


def test_tampering_is_detected(tmp_path):
    ledger = tmp_path / "shadow.jsonl"
    sink = AppendOnlyShadowClaimSink(ledger, identity_key=b"secret")
    sink.append(observation(1))
    event = json.loads(ledger.read_text(encoding="utf-8"))
    event["observation"]["false_accepts"] = 1
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")
    assert not sink.verify()
