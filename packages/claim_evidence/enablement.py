"""Explicit, read-only authority adapters. No automatic production activation.

Use existing governed snapshot records; never load evaluation labels as providers.
Adapter results require the existing acceptance and release gates before use.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from .authoritative_snapshot import AuthoritativeRecord, AuthoritativeSnapshot, MatchStatus
from .source_review import ReviewStatus, SourceReviewProvider


@dataclass(frozen=True)
class LookupResult:
    status: MatchStatus
    provider: str
    retrieved_at: datetime
    reason: str
    snapshot_version: str | None = None
    provenance_ids: tuple[str, ...] = field(
        default_factory=lambda: (f"LOOKUP_ATTEMPT:{uuid4().hex}",)
    )
    authority_class: str = "UNVERIFIED"
    production_authority: bool = field(default=False, init=False)
    release_truth: bool = field(default=False, init=False)

    @property
    def has_record_provenance(self) -> bool:
        """Attempt IDs document execution, not an authoritative record match."""
        if not isinstance(self.provenance_ids, tuple):
            return False
        return any(
            isinstance(p, str)
            and p.strip()
            and not p.strip().partition(":")[0].endswith("_ATTEMPT")
            for p in self.provenance_ids
        )


class SnapshotAuthorityAdapter:
    """Exact context/validity matching against an explicitly pinned snapshot.

    Pinning provides integrity, not authorization: the adapter is assessment-only.
    Missing comparison fields, scope or validity cannot produce MATCH.
    """

    def __init__(self, snapshot: AuthoritativeSnapshot | None = None, *, expected_sha256: str = ""):
        self.snapshot = snapshot
        self.expected_sha256 = expected_sha256
        self._integrity = self._fingerprint()

    def _fingerprint(self) -> str:
        return (
            hashlib.sha256(
                json.dumps(asdict(self.snapshot), sort_keys=True, default=str).encode()
            ).hexdigest()
            if self.snapshot
            else ""
        )

    def _lookup(
        self, keys: dict[str, str], comparisons: dict[str, object], on: date | None
    ) -> LookupResult:
        snapshot = self.snapshot
        now = datetime.now(UTC)

        def result(status, reason, records=()):
            return LookupResult(
                status,
                snapshot.source_system if snapshot else "NOT_CONFIGURED",
                now,
                reason,
                snapshot.dataset_version if snapshot else None,
                (f"LOOKUP_ATTEMPT:{uuid4().hex}",)
                + tuple(
                    f"{r.source_system}:{r.snapshot_id}:{r.source_record_id}:{r.record_hash}"
                    for r in records
                ),
                "PINNED_REFERENCE_ASSESSMENT" if snapshot and records else "UNVERIFIED",
            )

        if snapshot is None:
            return result(MatchStatus.NOT_AVAILABLE, "PROVIDER_NOT_CONFIGURED")
        if self._fingerprint() != self._integrity:
            return result(MatchStatus.CONFLICT, "SNAPSHOT_MUTATED_AFTER_CONFIGURATION")
        if not self.expected_sha256 or snapshot.sha256 != self.expected_sha256:
            return result(MatchStatus.NOT_AVAILABLE, "SNAPSHOT_INTEGRITY_NOT_PINNED")
        if type(on) is not date or not all(keys.values()) or not all(comparisons.values()):
            return result(MatchStatus.NOT_AVAILABLE, "REQUIRED_CONTEXT_MISSING")
        # Deliberately exact: no fuzzy names, OCR repair or implied payer scope.
        matches = [
            r for r in snapshot.records if all(r.values.get(k) == v for k, v in keys.items())
        ]
        current = [
            r
            for r in matches
            if r.effective_from <= on and (r.effective_to is None or on <= r.effective_to)
        ]
        if not matches:
            return result(MatchStatus.NO_MATCH, "NO_EXACT_KEY_MATCH")
        if not current:
            return result(MatchStatus.NOT_AVAILABLE, "NO_RECORD_VALID_ON_SERVICE_DATE")
        if len(current) != 1:
            return result(MatchStatus.CONFLICT, "NON_UNIQUE_VALID_RECORD", current)
        record: AuthoritativeRecord = current[0]
        if not all(
            (
                record.source_record_id,
                record.record_hash,
                snapshot.dataset_version,
                snapshot.source_system,
            )
        ):
            return result(MatchStatus.NOT_AVAILABLE, "RECORD_PROVENANCE_INCOMPLETE")
        if any(
            k not in record.values or record.values[k] is None or record.values[k] == ""
            for k in comparisons
        ):
            return result(MatchStatus.NOT_AVAILABLE, "REFERENCE_COMPARISON_FIELD_MISSING")
        if any(
            record.values[k] != v or (type(v) is bool and type(record.values[k]) is not bool)
            for k, v in comparisons.items()
        ):
            return result(MatchStatus.CONFLICT, "EXACT_CONTEXT_CONFLICT", current)
        return result(MatchStatus.MATCH, "EXACT_SCOPED_EFFECTIVE_RECORD", current)


class MemberAuthorityProvider(SnapshotAuthorityAdapter):
    def lookup(
        self, *, member_id: str, payer: str, service_date: date | None, patient_name: str, dob: str
    ) -> LookupResult:
        return self._lookup(
            {"member_id": member_id, "payer": payer},
            {"patient_name": patient_name, "dob": dob, "eligible": True},
            service_date,
        )


class ProviderAuthorityProvider(SnapshotAuthorityAdapter):
    def lookup(
        self, *, npi: str, provider_name: str, role: str, service_date: date | None
    ) -> LookupResult:
        return self._lookup(
            {"npi": npi, "provider_role": role}, {"provider_name": provider_name}, service_date
        )


class IdentityAuthorityProvider(SnapshotAuthorityAdapter):
    def lookup(
        self,
        *,
        member_id: str,
        payer: str,
        person_role: str,
        name: str,
        dob: str,
        service_date: date | None,
    ) -> LookupResult:
        if person_role not in {"patient", "subscriber", "insured"}:
            return LookupResult(
                MatchStatus.NOT_AVAILABLE, "IDENTITY", datetime.now(UTC), "INVALID_PERSON_ROLE"
            )
        return self._lookup(
            {"member_id": member_id, "payer": payer, "person_role": person_role},
            {"name": name, "dob": dob},
            service_date,
        )


class SourceStatus(StrEnum):
    AVAILABLE_UNVERIFIED = "AVAILABLE_UNVERIFIED"
    AVAILABLE = "AVAILABLE_UNVERIFIED"  # Compatibility alias; never verification.
    VERIFIED = "VERIFIED"
    UNREADABLE = "UNREADABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class SourceBinding:
    package_id: str
    page_id: str
    attachment_id: str
    path: Path
    sha256: str
    boundary_provenance_id: str
    value_region_provenance_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceResult:
    status: SourceStatus
    reason: str
    retrieved_at: datetime
    provenance_ids: tuple[str, ...] = field(
        default_factory=lambda: (f"LOOKUP_ATTEMPT:{uuid4().hex}",)
    )
    verification_available: bool = False

    @property
    def evidence_state(self) -> str:
        if self.status == SourceStatus.VERIFIED:
            return "VALUE_VERIFIED"
        if self.status == SourceStatus.AVAILABLE_UNVERIFIED:
            return "VERIFICATION_AVAILABLE" if self.verification_available else "FILE_PRESENT"
        return self.status.value

    # Presence and provenance do not establish correctness or resolve overprint.
    resolves_source_review: bool = field(default=False, init=False)
    production_authority: bool = field(default=False, init=False)
    release_truth: bool = field(default=False, init=False)


class SourceEvidenceProvider:
    """Lookup only caller-configured local bindings; never infer attachments."""

    def __init__(
        self,
        bindings: tuple[SourceBinding, ...] = (),
        *,
        reviews: SourceReviewProvider | None = None,
    ):
        self.bindings = bindings
        self.reviews = reviews

    def lookup(
        self,
        *,
        package_id: str,
        page_id: str,
        attachment_id: str,
        field_name: str = "",
        region_provenance_id: str = "",
    ) -> SourceResult:
        now = datetime.now(UTC)
        matches = [
            b
            for b in self.bindings
            if (b.package_id, b.page_id, b.attachment_id) == (package_id, page_id, attachment_id)
        ]
        if not all((package_id, page_id, attachment_id)) or not matches:
            return SourceResult(SourceStatus.NOT_AVAILABLE, "NO_CONFIGURED_SOURCE_BINDING", now)
        if len(matches) != 1:
            return SourceResult(SourceStatus.CONFLICT, "NON_UNIQUE_SOURCE_BINDING", now)
        binding = matches[0]
        if (
            not binding.boundary_provenance_id
            or not binding.value_region_provenance_ids
            or not all(binding.value_region_provenance_ids)
        ):
            return SourceResult(SourceStatus.NOT_AVAILABLE, "SOURCE_PROVENANCE_INCOMPLETE", now)
        try:
            actual = hashlib.sha256(binding.path.read_bytes()).hexdigest()
        except OSError:
            return SourceResult(SourceStatus.NOT_AVAILABLE, "SOURCE_ATTACHMENT_UNAVAILABLE", now)
        if actual != binding.sha256:
            return SourceResult(SourceStatus.CONFLICT, "SOURCE_CONTENT_CHANGED", now)
        provenance = (binding.boundary_provenance_id, *binding.value_region_provenance_ids)
        if (
            self.reviews
            and field_name
            and region_provenance_id in binding.value_region_provenance_ids
        ):
            review = self.reviews.lookup(
                package_id=package_id,
                page_id=page_id,
                attachment_id=attachment_id,
                source_sha256=actual,
                region_provenance_id=region_provenance_id,
                field_name=field_name,
            )
            if review.governed:
                status = {
                    ReviewStatus.CONFIRMED_VALUE: SourceStatus.VERIFIED,
                    ReviewStatus.CONFIRMED_UNREADABLE: SourceStatus.UNREADABLE,
                    ReviewStatus.CONFIRMED_CONFLICT: SourceStatus.CONFLICT,
                }.get(review.status, SourceStatus.AVAILABLE_UNVERIFIED)
                return SourceResult(
                    status, review.reason, now, provenance + review.provenance_ids, True
                )
        verification_available = bool(
            self.reviews
            and self.reviews.policy_id
            and self.reviews.authorized_reviewers
            and self.reviews.expected_sha256
            and field_name
            and region_provenance_id in binding.value_region_provenance_ids
        )
        return SourceResult(
            SourceStatus.AVAILABLE_UNVERIFIED,
            "SOURCE_BYTES_AND_PROVENANCE_AVAILABLE",
            now,
            (binding.boundary_provenance_id, *binding.value_region_provenance_ids),
            verification_available,
        )
