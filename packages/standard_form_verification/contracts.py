from enum import StrEnum

from pydantic import Field, model_validator

from packages.domain.common import DomainModel
from packages.document_taxonomy.taxonomy import DocumentClass


class StandardFormStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"


class StandardFormVerification(DomainModel):
    candidate_family: DocumentClass
    status: StandardFormStatus
    verification_score: float = Field(ge=0, le=1)
    supporting_evidence_classes: tuple[str, ...] = ()
    contradicting_evidence_classes: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    template_version: str | None = None
    verification_policy_version: str = "standard-form-verification-v1"
    eligible_for_fixed_extractor: bool = False

    @model_validator(mode="after")
    def fixed_extractor_is_fail_closed(self):
        if self.candidate_family not in {DocumentClass.CMS1500, DocumentClass.UB04}:
            raise ValueError("standard verification supports only CMS1500 and UB04")
        if self.eligible_for_fixed_extractor != (self.status == StandardFormStatus.VERIFIED):
            raise ValueError("only VERIFIED may be eligible for a fixed extractor")
        return self
