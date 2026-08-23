"""Classification contracts answer what a page is, never how it is extracted."""
from __future__ import annotations

from pydantic import Field, model_validator

from packages.domain.common import DomainModel
from .taxonomy import DocumentClass, DocumentTaxonomyV1


TOP_LEVEL_CLASSES = {
    DocumentClass.CLAIM, DocumentClass.CLAIM_SUPPORT,
    DocumentClass.NON_CLAIM, DocumentClass.UNKNOWN,
}


class DocumentClassification(DomainModel):
    document_id: str
    page_id: str
    top_level_class: DocumentClass
    document_family: DocumentClass
    document_subtype: DocumentClass
    structured: bool
    claim_related: bool
    standard_candidate: bool
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: tuple[str, ...] = ()
    contradicting_evidence: tuple[str, ...] = ()
    ambiguity_reason: str | None = None
    taxonomy_version: str = DocumentTaxonomyV1.version
    classifier_version: str

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.top_level_class not in TOP_LEVEL_CLASSES:
            raise ValueError("top_level_class must be CLAIM, CLAIM_SUPPORT, NON_CLAIM, or UNKNOWN")
        if self.document_subtype != DocumentClass.UNKNOWN:
            ancestors = DocumentTaxonomyV1.ancestors(self.document_subtype)
            if self.top_level_class not in ancestors and self.top_level_class != self.document_subtype:
                raise ValueError("document subtype is outside its top-level taxonomy class")
        if self.standard_candidate and self.top_level_class != DocumentClass.CLAIM:
            raise ValueError("only a claim may be a standard candidate")
        return self
