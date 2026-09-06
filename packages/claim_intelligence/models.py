from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExtractionState(StrEnum):
    EXTRACTED_CONFIDENT = "EXTRACTED_CONFIDENT"
    EXTRACTED_AMBIGUOUS = "EXTRACTED_AMBIGUOUS"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class AuthorityState(StrEnum):
    AUTHORITATIVE_MATCH = "AUTHORITATIVE_MATCH"
    AUTHORITATIVE_CONFLICT = "AUTHORITATIVE_CONFLICT"
    AUTHORITATIVE_NOT_AVAILABLE = "AUTHORITATIVE_NOT_AVAILABLE"
    AUTHORITATIVE_NOT_REQUIRED = "AUTHORITATIVE_NOT_REQUIRED"


@dataclass(frozen=True)
class CandidateEvidence:
    source: str
    confidence: float | None = None
    page_id: str | None = None
    crop_hash: str | None = None
    localization_region: str | None = None
    independent_group: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    value: str
    evidence: tuple[CandidateEvidence, ...] = ()


@dataclass
class FieldNode:
    name: str
    candidates: list[Candidate] = field(default_factory=list)
    extraction_state: ExtractionState = ExtractionState.EXTRACTION_FAILED
    authority_state: AuthorityState = AuthorityState.AUTHORITATIVE_NOT_AVAILABLE
    selected_candidate_id: str | None = None
    critical: bool = False

    def selected(self) -> Candidate | None:
        if self.selected_candidate_id is None:
            return None
        for candidate in self.candidates:
            if candidate.candidate_id == self.selected_candidate_id:
                return candidate
        return None


@dataclass(frozen=True)
class ServiceLine:
    line_id: str
    service_date: str | None = None
    procedure_code: str | None = None
    diagnosis_pointer: str | None = None
    charge: str | None = None


@dataclass
class ClaimGraph:
    claim_id: str
    form_type: str
    fields: dict[str, FieldNode] = field(default_factory=dict)
    service_lines: list[ServiceLine] = field(default_factory=list)
    statement_start: str | None = None
    statement_end: str | None = None

    def field(self, name: str) -> FieldNode | None:
        return self.fields.get(name)
