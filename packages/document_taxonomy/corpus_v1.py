"""Qualified ROUTING_TAXONOMY_CORPUS_V1 contracts; assets remain outside Git."""
from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import Field, model_validator

from packages.domain.common import DomainModel
from packages.processing_routes.contracts import ProcessingRoute

from .taxonomy import DocumentClass, DocumentTaxonomyV1

CORPUS_VERSION = "ROUTING_TAXONOMY_CORPUS_V1"


class IndependenceAttestation(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class PhiStatus(StrEnum):
    PHI_FREE = "PHI_FREE"
    APPROVED_DEIDENTIFIED = "APPROVED_DEIDENTIFIED"
    AUTHORIZED_CONTROLLED_TEST_DATA = "AUTHORIZED_CONTROLLED_TEST_DATA"
    UNKNOWN = "UNKNOWN"


class UsageStatus(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    PUBLICLY_USABLE = "PUBLICLY_USABLE"
    INTERNAL_APPROVED = "INTERNAL_APPROVED"
    LICENSED_FOR_EVALUATION = "LICENSED_FOR_EVALUATION"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


class StandardFormAuthority(StrEnum):
    VERIFIED_STANDARD = "VERIFIED_STANDARD"
    NOT_STANDARD = "NOT_STANDARD"
    AMBIGUOUS = "AMBIGUOUS"


class HierarchicalTruthLabel(DomainModel):
    top_level_class: DocumentClass
    document_family: DocumentClass
    subtype: DocumentClass
    expected_processing_route: ProcessingRoute

    @model_validator(mode="after")
    def valid_path(self):
        if self.subtype == DocumentClass.UNKNOWN:
            if (self.top_level_class, self.document_family) != (
                DocumentClass.UNKNOWN, DocumentClass.UNKNOWN
            ):
                raise ValueError("UNKNOWN truth must use UNKNOWN top-level and family labels")
            return self
        if DocumentTaxonomyV1.children_of(self.subtype):
            raise ValueError("truth subtype must be a leaf in DocumentTaxonomyV1")
        ancestors = DocumentTaxonomyV1.ancestors(self.subtype)
        expected_top_level = next(
            item for item in ancestors
            if item in {DocumentClass.CLAIM, DocumentClass.CLAIM_SUPPORT, DocumentClass.NON_CLAIM}
        )
        expected_family = DocumentTaxonomyV1.parent_of(self.subtype)
        if self.top_level_class != expected_top_level:
            raise ValueError("truth top-level class does not match the subtype path")
        if self.document_family != expected_family:
            raise ValueError("truth document family must be the subtype's immediate parent")
        return self


class SourceLineageRecord(DomainModel):
    source_family_id: str
    source_description: str
    origin: str
    acquisition_method: str
    renderer: str
    template_lineage: str
    created_or_acquired_at: str
    relationship_to_other_sources: str
    independence_rationale: str
    license_or_usage_status: UsageStatus
    phi_status: PhiStatus
    source_independence_attestation: IndependenceAttestation

    @property
    def qualified(self) -> bool:
        return (self.source_independence_attestation == IndependenceAttestation.PASS
                and self.phi_status in {PhiStatus.PHI_FREE, PhiStatus.APPROVED_DEIDENTIFIED,
                                        PhiStatus.AUTHORIZED_CONTROLLED_TEST_DATA}
                and self.license_or_usage_status in {UsageStatus.AUTHORIZED,
                                                     UsageStatus.PUBLICLY_USABLE,
                                                     UsageStatus.INTERNAL_APPROVED,
                                                     UsageStatus.LICENSED_FOR_EVALUATION})


class RoutingTaxonomyPageRecord(DomainModel):
    document_id: str
    page_id: str
    truth_top_level_class: DocumentClass
    truth_document_family: DocumentClass
    truth_subtype: DocumentClass
    expected_processing_route: ProcessingRoute
    source_family: str
    source_instance: str
    renderer_family: str
    template_lineage: str
    layout_family: str
    acquisition_method: str
    digital_or_scan: str
    dpi_bucket: str
    quality_bucket: str
    degradation_family: str
    standard_form_authority: StandardFormAuthority
    reviewer_1_label: HierarchicalTruthLabel
    reviewer_2_label: HierarchicalTruthLabel | None = None
    adjudicated_label: HierarchicalTruthLabel
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")
    layout_fingerprint: str = Field(min_length=8)
    base_asset_id: str
    phi_status: PhiStatus
    license_or_usage_status: UsageStatus
    image_readable: bool
    split_eligibility: bool
    corpus_version: str = CORPUS_VERSION

    @model_validator(mode="after")
    def truth_matches_adjudication(self):
        truth = (self.truth_top_level_class, self.truth_document_family,
                 self.truth_subtype, self.expected_processing_route)
        adjudicated = (self.adjudicated_label.top_level_class,
                       self.adjudicated_label.document_family,
                       self.adjudicated_label.subtype,
                       self.adjudicated_label.expected_processing_route)
        if truth != adjudicated:
            raise ValueError("manifest truth must equal the adjudicated hierarchical label")
        return self


class QualifiedRoutingCorpusManifest(DomainModel):
    corpus_version: str = CORPUS_VERSION
    sources: tuple[SourceLineageRecord, ...]
    pages: tuple[RoutingTaxonomyPageRecord, ...]
    minimum_pages: int = 1000
    minimum_sources_per_priority_class: int = 3
    double_review_minimum_rate: float = .10

    def hashes(self) -> dict[str, str]:
        stable = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        assets = sorted({page.file_sha256 for page in self.pages})
        truth = sorted(({"page_id": page.page_id, "truth": page.adjudicated_label.model_dump(mode="json")}
                        for page in self.pages), key=lambda row: row["page_id"])
        sources = sorted((source.model_dump(mode="json") for source in self.sources),
                         key=lambda row: row["source_family_id"])
        review = sorted(({"page_id": page.page_id,
                         "reviewer_1": page.reviewer_1_label.model_dump(mode="json"),
                         "reviewer_2": (page.reviewer_2_label.model_dump(mode="json")
                                        if page.reviewer_2_label else None),
                         "adjudicated": page.adjudicated_label.model_dump(mode="json")}
                         for page in self.pages), key=lambda row: row["page_id"])
        manifest = self.model_dump(mode="json")
        return {"manifest_hash": hashlib.sha256(stable(manifest)).hexdigest(),
                "asset_hash": hashlib.sha256(stable(assets)).hexdigest(),
                "truth_hash": hashlib.sha256(stable(truth)).hexdigest(),
                "source_lineage_hash": hashlib.sha256(stable(sources)).hexdigest(),
                "review_adjudication_hash": hashlib.sha256(stable(review)).hexdigest()}
