"""Form-specific verification evidence. Verifiers cannot emit a final route."""
from pydantic import Field

from packages.domain.common import DomainModel
from .taxonomy import DocumentClass


class FormVerificationEvidence(DomainModel):
    proposed_form: DocumentClass
    verified: bool
    score: float = Field(ge=0, le=1)
    required_traits_present: tuple[str, ...]
    missing_traits: tuple[str, ...]
    contradiction_codes: tuple[str, ...]
    verifier_version: str = "form-verification-v1"


REQUIRED_TRAITS = {
    DocumentClass.CMS1500: frozenset({"patient_insured_blocks", "diagnosis_pointer_area", "professional_service_grid"}),
    DocumentClass.UB04: frozenset({"form_locator_structure", "revenue_code_column", "institutional_service_grid"}),
}


def verify_standard_form(proposed_form: DocumentClass, observed_traits: set[str]) -> FormVerificationEvidence:
    if proposed_form not in REQUIRED_TRAITS:
        raise ValueError("form verification is limited to CMS1500 and UB04")
    required = REQUIRED_TRAITS[proposed_form]
    present = required & observed_traits
    missing = required - observed_traits
    score = len(present) / len(required)
    return FormVerificationEvidence(proposed_form=proposed_form, verified=not missing, score=score,
        required_traits_present=tuple(sorted(present)), missing_traits=tuple(sorted(missing)),
        contradiction_codes=("REQUIRED_FORM_TRAITS_MISSING",) if missing else ())
