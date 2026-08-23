from datetime import UTC, datetime, timedelta
from uuid import uuid4

from packages.domain.review import ReviewTask
from packages.review_priority import review_priority_key


def task(**changes):
    values = {
        "claim_id": uuid4(), "document_id": uuid4(), "field_id": uuid4(),
        "field_name": "patient_name", "page_number": 1,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(changes)
    return ReviewTask(**values)


def test_single_blocker_breaks_priority_tie_after_sla_value_and_criticality():
    now = datetime(2026, 1, 2, tzinfo=UTC)
    due = now + timedelta(hours=1)
    ordinary = task(sla_due_at=due, claim_value_usd=100, single_blocker_claim=False)
    unlock = task(sla_due_at=due, claim_value_usd=100, single_blocker_claim=True)

    ranked = sorted(
        [ordinary, unlock],
        key=lambda item: review_priority_key(item, criticality="C3", now=now),
    )
    assert ranked[0] is unlock


def test_claim_unlock_value_prioritizes_higher_blocker_impact():
    now = datetime.now(UTC)
    due = now + timedelta(minutes=5)
    low = task(sla_due_at=due, claim_unlock_value=0.25)
    high = task(sla_due_at=due, claim_unlock_value=1.0)

    ranked = sorted(
        [low, high],
        key=lambda item: review_priority_key(item, criticality="C3", now=now),
    )

    assert ranked[0] is high


def test_review_task_carries_only_targeted_blocker_context():
    review = task(
        selected_candidate_id="candidate-1",
        candidate_evidence=[{"candidate_id": "candidate-1", "class": "E1"}],
        policy_requirement=[["E2", "E3", "E4"]], missing_evidence=["E2"],
        reason_for_review=["MISSING_E2_INDEPENDENT_CONFIRMATION"],
        claim_impact="single review unlocks claim", single_blocker_claim=True,
        route_id="route-1", route_status="PRODUCTION_APPROVED",
    )
    assert review.field_name == "patient_name"
    assert review.single_blocker_claim is True
    assert review.missing_evidence == ["E2"]
