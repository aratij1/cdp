"""Pinned, explicitly governed source-review assessment; never release truth."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class ReviewStatus(StrEnum):
    CONFIRMED_VALUE = "CONFIRMED_VALUE"
    CONFIRMED_UNREADABLE = "CONFIRMED_UNREADABLE"
    CONFIRMED_CONFLICT = "CONFIRMED_CONFLICT"
    NOT_REVIEWED = "NOT_REVIEWED"


@dataclass(frozen=True)
class SourceReviewRecord:
    package_id: str
    page_id: str
    attachment_id: str
    source_sha256: str
    region_provenance_id: str
    field_name: str
    status: ReviewStatus
    record_id: str
    reviewer_id: str
    policy_id: str
    reviewed_at: datetime
    # Sensitive value stays in the caller's governed data store, never telemetry.
    confirmed_value: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ReviewAssessment:
    status: ReviewStatus
    reason: str
    provenance_ids: tuple[str, ...]
    confirmed_value: str | None = field(default=None, repr=False)
    governed: bool = False
    production_authority: bool = field(default=False, init=False)
    release_truth: bool = field(default=False, init=False)


def review_digest(records: tuple[SourceReviewRecord, ...]) -> str:
    return hashlib.sha256(
        json.dumps([asdict(r) for r in records], sort_keys=True, default=str).encode()
    ).hexdigest()


class SourceReviewProvider:
    """Only externally provisioned, pinned reviews from an explicit reviewer registry.

    The host must govern the registry/policy/pin together. A content hash alone is
    not authorization. This assessment does not write claim values or release labels.
    """

    def __init__(
        self,
        records: tuple[SourceReviewRecord, ...] = (),
        *,
        expected_sha256: str = "",
        authorized_reviewers: frozenset[str] = frozenset(),
        policy_id: str = "",
    ):
        self.records = records
        self.expected_sha256 = expected_sha256
        self.authorized_reviewers = authorized_reviewers
        self.policy_id = policy_id

    def lookup(
        self,
        *,
        package_id: str,
        page_id: str,
        attachment_id: str,
        source_sha256: str,
        region_provenance_id: str,
        field_name: str,
    ) -> ReviewAssessment:
        attempt = (f"SOURCE_REVIEW_ATTEMPT:{uuid4().hex}",)

        def unavailable(reason: str) -> ReviewAssessment:
            return ReviewAssessment(ReviewStatus.NOT_REVIEWED, reason, attempt)

        if not self.records or not self.policy_id or not self.authorized_reviewers:
            return unavailable("GOVERNED_REVIEW_NOT_CONFIGURED")
        if not self.expected_sha256 or review_digest(self.records) != self.expected_sha256:
            return unavailable("REVIEW_INTEGRITY_NOT_PINNED")
        key = (package_id, page_id, attachment_id, source_sha256, region_provenance_id, field_name)
        if not all(key):
            return unavailable("REVIEW_SCOPE_INCOMPLETE")
        matches = [
            r
            for r in self.records
            if (
                r.package_id,
                r.page_id,
                r.attachment_id,
                r.source_sha256,
                r.region_provenance_id,
                r.field_name,
            )
            == key
        ]
        if len(matches) != 1:
            return unavailable("REVIEW_MISSING_OR_NON_UNIQUE")
        record = matches[0]
        if (
            record.reviewer_id not in self.authorized_reviewers
            or record.policy_id != self.policy_id
            or not record.record_id
            or record.reviewed_at.tzinfo is None
            or record.reviewed_at > datetime.now(UTC)
        ):
            return unavailable("REVIEW_GOVERNANCE_INVALID")
        if (
            not isinstance(record.status, ReviewStatus)
            or record.status == ReviewStatus.NOT_REVIEWED
        ):
            return unavailable("NO_REVIEW_CONCLUSION")
        if (record.status == ReviewStatus.CONFIRMED_VALUE and not record.confirmed_value) or (
            record.status != ReviewStatus.CONFIRMED_VALUE and record.confirmed_value is not None
        ):
            return unavailable("REVIEW_CONCLUSION_INVALID")
        return ReviewAssessment(
            record.status,
            "GOVERNED_SCOPED_REVIEW",
            attempt + (f"SOURCE_REVIEW_RECORD:{record.record_id}",),
            record.confirmed_value,
            True,
        )
