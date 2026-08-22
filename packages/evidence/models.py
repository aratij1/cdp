from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from packages.domain.common import DomainModel, new_id


class EvidenceClass(StrEnum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"
    E5 = "E5"
    E6 = "E6"
    E7 = "E7"
    E8 = "E8"


class EvidenceItem(DomainModel):
    evidence_id: UUID = Field(default_factory=new_id)
    evidence_class: EvidenceClass
    evidence_type: str
    evidence_family: str
    source: str
    value: str | None = None
    supports_candidate_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    independent: bool = False
    authoritative: bool = False
    deterministic: bool = False
    version: str | None = None
    metadata: dict = Field(default_factory=dict)


class EvidenceBundle(DomainModel):
    field_name: str
    candidate_value: str | None = None
    items: list[EvidenceItem] = Field(default_factory=list)

    @property
    def available_classes(self) -> set[EvidenceClass]:
        return {item.evidence_class for item in self.items if item.evidence_class != EvidenceClass.E0}

    @property
    def independent_families(self) -> set[str]:
        return {item.evidence_family for item in self.items if item.independent}
