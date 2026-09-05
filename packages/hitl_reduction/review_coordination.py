from __future__ import annotations

import json
import unicodedata
from hashlib import sha256
from typing import Any

BLIND_TASK_FIELDS = {
    "blind_task_id",
    "field_instance_id",
    "field_name",
    "document_id",
    "page_id",
    "page_sha256",
    "crop_sha256",
    "crop_reference",
    "criticality",
    "required_independent_reviews",
    "adjudication_required_on_disagreement",
}


def canonical_reviewer_id(value: str) -> str:
    """Return the comparison identity used for independence checks."""
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(payload: Any) -> str:
    return sha256(_canonical_bytes(payload)).hexdigest()


def _validate_queue(queue: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if queue.get("schema_version") != "hitl-reduction-blind-review-v1":
        raise ValueError("UNSUPPORTED_BLIND_REVIEW_QUEUE")
    seal = queue.get("prediction_seal_sha256")
    if not isinstance(seal, str) or len(seal) != 64:
        raise ValueError("PREDICTION_SEAL_REQUIRED")
    try:
        int(seal, 16)
    except ValueError as exc:
        raise ValueError("PREDICTION_SEAL_INVALID") from exc
    tasks = queue.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("BLIND_REVIEW_TASKS_REQUIRED")
    task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task) != BLIND_TASK_FIELDS:
            raise ValueError("BLIND_TASK_SCHEMA_OR_LEAKAGE_VIOLATION")
        task_id = task.get("blind_task_id")
        if not isinstance(task_id, str) or len(task_id) != 64:
            raise ValueError("BLIND_TASK_ID_INVALID")
        try:
            int(task_id, 16)
        except ValueError as exc:
            raise ValueError("BLIND_TASK_ID_INVALID") from exc
        if task_id in task_ids:
            raise ValueError("DUPLICATE_BLIND_TASK_ID")
        task_ids.add(task_id)
        required = task.get("required_independent_reviews")
        if required not in {1, 2}:
            raise ValueError("UNSUPPORTED_INDEPENDENT_REVIEW_COUNT")
    return seal, sorted(tasks, key=lambda item: item["blind_task_id"])


def build_review_assignments(
    blind_queue: dict[str, Any], reviewer_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Create isolated prediction-blind reviewer packs and a coordinator manifest."""
    seal, tasks = _validate_queue(blind_queue)
    reviewers = [value.strip() for value in reviewer_ids]
    if any(not value for value in reviewers):
        raise ValueError("REVIEWER_ID_REQUIRED")
    canonical = [canonical_reviewer_id(value) for value in reviewers]
    if len(canonical) != len(set(canonical)):
        raise ValueError("REVIEWER_IDENTITIES_NOT_INDEPENDENT")

    maximum_reviews = max(int(task["required_independent_reviews"]) for task in tasks)
    minimum_people = 3 if maximum_reviews == 2 else 1
    if len(reviewers) < minimum_people:
        raise ValueError(f"AT_LEAST_{minimum_people}_INDEPENDENT_REVIEWERS_REQUIRED")

    assignments: dict[str, list[dict[str, Any]]] = {reviewer: [] for reviewer in reviewers}
    coordinator_tasks: list[dict[str, Any]] = []
    for task in tasks:
        required = int(task["required_independent_reviews"])
        start = int(task["blind_task_id"][:16], 16) % len(reviewers)
        assigned = [reviewers[(start + offset) % len(reviewers)] for offset in range(required)]
        adjudicators = [reviewer for reviewer in reviewers if reviewer not in assigned]
        if required == 2 and not adjudicators:
            raise ValueError("INDEPENDENT_ADJUDICATOR_REQUIRED")
        for reviewer in assigned:
            assignments[reviewer].append(dict(task))
        coordinator_tasks.append(
            {
                "blind_task_id": task["blind_task_id"],
                "assigned_reviewer_ids": assigned,
                "eligible_adjudicator_ids": adjudicators,
            }
        )

    manifest_payload = {
        "schema_version": "hitl-reduction-review-assignment-v1",
        "prediction_seal_sha256": seal,
        "reviewer_count": len(reviewers),
        "task_count": len(tasks),
        "review_assignment_count": sum(len(rows) for rows in assignments.values()),
        "tasks": coordinator_tasks,
    }
    assignment_seal = _digest(manifest_payload)
    outputs: dict[str, dict[str, Any]] = {
        "review_assignment_manifest": {
            **manifest_payload,
            "review_assignment_seal_sha256": assignment_seal,
        }
    }
    for index, reviewer in enumerate(reviewers, 1):
        outputs[f"reviewer_{index:03d}"] = {
            "schema_version": "hitl-reduction-reviewer-pack-v1",
            "prediction_seal_sha256": seal,
            "review_assignment_seal_sha256": assignment_seal,
            "reviewer_id": reviewer,
            "tasks": assignments[reviewer],
        }
    return outputs


def verify_review_assignment(manifest: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when a coordinator manifest no longer matches its seal."""
    payload = dict(manifest)
    seal = payload.pop("review_assignment_seal_sha256", None)
    if payload.get("schema_version") != "hitl-reduction-review-assignment-v1":
        raise ValueError("UNSUPPORTED_REVIEW_ASSIGNMENT_MANIFEST")
    if not isinstance(seal, str) or _digest(payload) != seal:
        raise ValueError("REVIEW_ASSIGNMENT_SEAL_INVALID")
    return {
        "schema_version": "hitl-reduction-review-assignment-verification-v1",
        "status": "VERIFIED",
        "prediction_seal_sha256": payload["prediction_seal_sha256"],
        "review_assignment_seal_sha256": seal,
        "reviewer_count": payload["reviewer_count"],
        "task_count": payload["task_count"],
        "review_assignment_count": payload["review_assignment_count"],
    }
