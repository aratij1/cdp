"""Contracts which separate form identity from extraction geometry authority.

Recognising a CMS-1500 or UB-04 page is not proof that fixed coordinates are
safe.  The fixed extractor is authorized only by a compatible template plus
an accepted registration with valid transformed corners.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from packages.document_taxonomy.taxonomy import DocumentClass
from packages.domain.common import DomainModel
from packages.domain.registration import RegistrationEvidence
from packages.standard_form_verification.contracts import (
    StandardFormStatus,
    StandardFormVerification,
)
from packages.template_compatibility import (
    TemplateCompatibilityEvidence,
    TemplateCompatibilityStatus,
)


class ExtractionGeometryMode(StrEnum):
    REGISTERED_FIXED = "REGISTERED_FIXED"
    ANCHOR_RELATIVE = "ANCHOR_RELATIVE"
    STRUCTURAL_LAYOUT = "STRUCTURAL_LAYOUT"
    SAFE_FALLBACK = "SAFE_FALLBACK"
    UNAVAILABLE = "UNAVAILABLE"


class FormIdentityStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    AMBIGUOUS = "AMBIGUOUS"


class FormIdentityDecision(DomainModel):
    family: DocumentClass
    status: FormIdentityStatus
    score: float = Field(ge=0, le=1)
    template_version: str | None = None
    supporting_evidence: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    policy_version: str = "form-identity-decision-v1"

    @classmethod
    def from_standard_verification(
        cls, verification: StandardFormVerification
    ) -> FormIdentityDecision:
        status = {
            StandardFormStatus.VERIFIED: FormIdentityStatus.VERIFIED,
            StandardFormStatus.NOT_VERIFIED: FormIdentityStatus.NOT_VERIFIED,
            StandardFormStatus.AMBIGUOUS: FormIdentityStatus.AMBIGUOUS,
        }[verification.status]
        return cls(
            family=verification.candidate_family,
            status=status,
            score=verification.verification_score,
            template_version=verification.template_version,
            supporting_evidence=verification.supporting_evidence_classes,
            contradictions=verification.contradicting_evidence_classes,
            reason_codes=verification.reason_codes,
        )


class ExtractionGeometryDecision(DomainModel):
    mode: ExtractionGeometryMode
    form_identity: FormIdentityDecision
    template_id: str | None = None
    template_version: str | None = None
    compatibility: TemplateCompatibilityEvidence | None = None
    registration: RegistrationEvidence | None = None
    transformed_geometry_valid: bool = False
    structural_confidence: float | None = Field(default=None, ge=0, le=1)
    reason_codes: tuple[str, ...] = ()
    policy_version: str = "extraction-geometry-policy-v1"

    @property
    def authorizes_fixed_roi(self) -> bool:
        return self.mode == ExtractionGeometryMode.REGISTERED_FIXED

    @model_validator(mode="after")
    def fixed_geometry_is_fail_closed(self):
        if self.mode != ExtractionGeometryMode.REGISTERED_FIXED:
            return self
        if self.form_identity.status != FormIdentityStatus.VERIFIED:
            raise ValueError("REGISTERED_FIXED_REQUIRES_VERIFIED_FORM_IDENTITY")
        if self.compatibility is None or self.compatibility.status == TemplateCompatibilityStatus.INCOMPATIBLE:
            raise ValueError("REGISTERED_FIXED_REQUIRES_COMPATIBLE_TEMPLATE")
        if self.registration is None or not self.registration.accepted:
            raise ValueError("REGISTERED_FIXED_REQUIRES_ACCEPTED_REGISTRATION")
        if not self.transformed_geometry_valid or self.registration.corner_validity is not True:
            raise ValueError("REGISTERED_FIXED_REQUIRES_VALID_TRANSFORMED_GEOMETRY")
        if not self.template_id or not self.template_version:
            raise ValueError("REGISTERED_FIXED_REQUIRES_TEMPLATE_LINEAGE")
        return self
