"""PHI-safe governed contracts for Phase 7A.12 corpus intake and review."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from packages.document_taxonomy.corpus_v1 import (
    CORPUS_VERSION,
    HierarchicalTruthLabel,
    IndependenceAttestation,
    PhiStatus,
    UsageStatus,
)
from packages.document_taxonomy.policy import ROUTE_BY_CLASS
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.domain.common import DomainModel
from packages.processing_routes.contracts import ProcessingRoute

INTAKE_SCHEMA_VERSION = "phase7a12-corpus-intake-v1.0.0"
SOURCE_ATTESTATION_SCHEMA_VERSION = "phase7a12-source-attestation-v1.0.0"
REVIEW_SCHEMA_VERSION = "phase7a12-blind-review-v1.0.0"


class QualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    EXCLUDED = "EXCLUDED"
    PENDING_REVIEW = "PENDING_REVIEW"
    PENDING_ATTESTATION = "PENDING_ATTESTATION"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    PENDING_PHI_CLEARANCE = "PENDING_PHI_CLEARANCE"
    PENDING_ADJUDICATION = "PENDING_ADJUDICATION"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    REVIEWER_1_COMPLETE = "REVIEWER_1_COMPLETE"
    DOUBLE_REVIEW_COMPLETE = "DOUBLE_REVIEW_COMPLETE"
    PENDING_ADJUDICATION = "PENDING_ADJUDICATION"
    ADJUDICATED = "ADJUDICATED"


class StandardStatus(StrEnum):
    STANDARD = "STANDARD"
    NON_STANDARD = "NON_STANDARD"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    AMBIGUOUS = "AMBIGUOUS"


class StandardFamily(StrEnum):
    CMS1500 = "CMS1500"
    UB04 = "UB04"
    NONE = "NONE"
    AMBIGUOUS = "AMBIGUOUS"


class ConfidenceBucket(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AmbiguityReason(StrEnum):
    NONE = "NONE"
    ILLEGIBLE = "ILLEGIBLE"
    PARTIAL_PAGE = "PARTIAL_PAGE"
    MIXED_DOCUMENT = "MIXED_DOCUMENT"
    TAXONOMY_UNCLEAR = "TAXONOMY_UNCLEAR"
    STANDARD_FORM_UNCERTAIN = "STANDARD_FORM_UNCERTAIN"
    OTHER_CONTROLLED = "OTHER_CONTROLLED"


class CorpusAssetIntakeRecord(DomainModel):
    asset_id: str
    document_id: str
    page_id: str
    asset_uri: str
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")
    mime_type: str
    page_count: int = Field(gt=0)
    source_family_id: str
    source_instance_id: str
    template_lineage_id: str
    renderer_lineage_id: str
    layout_family: str
    acquisition_method: str
    degradation_family: str
    phi_status: PhiStatus
    usage_status: UsageStatus
    license_or_authorization_reference: str
    truth_top_level_class: DocumentClass
    truth_document_family: DocumentClass
    truth_subtype: DocumentClass
    expected_processing_route: ProcessingRoute
    review_status: ReviewStatus = ReviewStatus.PENDING
    split_eligibility: bool = False
    qualification_status: QualificationStatus = QualificationStatus.PENDING_ATTESTATION
    exclusion_reason_codes: tuple[str, ...] = ()
    corpus_version: str = CORPUS_VERSION
    intake_schema_version: str = INTAKE_SCHEMA_VERSION

    @model_validator(mode="after")
    def validate_declared_truth(self):
        HierarchicalTruthLabel(
            top_level_class=self.truth_top_level_class,
            document_family=self.truth_document_family,
            subtype=self.truth_subtype,
            expected_processing_route=self.expected_processing_route,
        )
        if ROUTE_BY_CLASS[self.truth_subtype] != self.expected_processing_route:
            raise ValueError("expected route must match the canonical route truth for the subtype")
        if not self.license_or_authorization_reference:
            raise ValueError("license_or_authorization_reference is required")
        return self

    def declared_label(self) -> HierarchicalTruthLabel:
        return HierarchicalTruthLabel(
            top_level_class=self.truth_top_level_class,
            document_family=self.truth_document_family,
            subtype=self.truth_subtype,
            expected_processing_route=self.expected_processing_route,
        )


class SourceLineageAttestation(DomainModel):
    source_family_id: str
    source_description: str
    origin_type: str
    acquisition_method: str
    template_lineage_id: str
    renderer_lineage_id: str
    relationship_to_other_sources: tuple[str, ...] = ()
    independence_rationale: str
    usage_status: UsageStatus
    phi_status: PhiStatus
    reviewer_id: str
    review_timestamp: datetime
    source_hash_manifest: str = Field(pattern=r"^[0-9a-f]{64}$")
    independence_status: IndependenceAttestation
    authorization_reference: str
    schema_version: str = SOURCE_ATTESTATION_SCHEMA_VERSION

    @property
    def qualified(self) -> bool:
        return (
            self.independence_status == IndependenceAttestation.PASS
            and self.phi_status
            in {
                PhiStatus.PHI_FREE,
                PhiStatus.APPROVED_DEIDENTIFIED,
                PhiStatus.AUTHORIZED_CONTROLLED_TEST_DATA,
            }
            and self.usage_status
            in {
                UsageStatus.AUTHORIZED,
                UsageStatus.PUBLICLY_USABLE,
                UsageStatus.INTERNAL_APPROVED,
                UsageStatus.LICENSED_FOR_EVALUATION,
            }
            and bool(self.authorization_reference)
        )


class BlindReviewRecord(DomainModel):
    reviewer_id: str
    review_session_id: str
    asset_id: str
    top_level_label: DocumentClass
    document_family: DocumentClass
    standard_status: StandardStatus
    standard_family: StandardFamily
    subtype: DocumentClass
    expected_processing_route: ProcessingRoute
    ambiguity: bool
    ambiguity_reason: AmbiguityReason
    confidence_bucket: ConfidenceBucket
    created_at: datetime
    blind_to_other_reviews: bool
    schema_version: str = REVIEW_SCHEMA_VERSION

    @model_validator(mode="after")
    def validate_review_semantics(self):
        label = HierarchicalTruthLabel(
            top_level_class=self.top_level_label,
            document_family=self.document_family,
            subtype=self.subtype,
            expected_processing_route=self.expected_processing_route,
        )
        if ROUTE_BY_CLASS[label.subtype] != label.expected_processing_route:
            raise ValueError("review route truth must match the canonical subtype route")
        expected_status = (
            StandardStatus.STANDARD
            if self.subtype in {DocumentClass.CMS1500, DocumentClass.UB04}
            else StandardStatus.NON_STANDARD
            if self.top_level_label == DocumentClass.CLAIM
            else StandardStatus.NOT_APPLICABLE
        )
        if not self.ambiguity and self.standard_status != expected_status:
            raise ValueError("standard status conflicts with the reviewed taxonomy label")
        expected_family = (
            StandardFamily(self.subtype.value)
            if self.subtype in {DocumentClass.CMS1500, DocumentClass.UB04}
            else StandardFamily.NONE
        )
        if not self.ambiguity and self.standard_family != expected_family:
            raise ValueError("standard family conflicts with the reviewed subtype")
        if self.ambiguity != (self.ambiguity_reason != AmbiguityReason.NONE):
            raise ValueError("ambiguity flag and controlled ambiguity reason must agree")
        if not self.blind_to_other_reviews:
            raise ValueError("review is not eligible unless reviewer blindness is attested")
        return self

    def label(self) -> HierarchicalTruthLabel:
        return HierarchicalTruthLabel(
            top_level_class=self.top_level_label,
            document_family=self.document_family,
            subtype=self.subtype,
            expected_processing_route=self.expected_processing_route,
        )


class AdjudicationRecord(DomainModel):
    adjudicator_id: str
    adjudication_session_id: str
    asset_id: str
    final_label: HierarchicalTruthLabel
    reason_code: str
    created_at: datetime

    @model_validator(mode="after")
    def validate_route_truth(self):
        if ROUTE_BY_CLASS[self.final_label.subtype] != self.final_label.expected_processing_route:
            raise ValueError("adjudicated route truth must match the canonical subtype route")
        return self


class CorpusIntakeBatch(DomainModel):
    schema_version: str = INTAKE_SCHEMA_VERSION
    assets: tuple[CorpusAssetIntakeRecord, ...] = ()
    source_attestations: tuple[SourceLineageAttestation, ...] = ()
    reviews: tuple[BlindReviewRecord, ...] = ()
    adjudications: tuple[AdjudicationRecord, ...] = ()

    @model_validator(mode="after")
    def unique_governed_identifiers(self):
        for name, values in {
            "asset_id": [item.asset_id for item in self.assets],
            "page_id": [item.page_id for item in self.assets],
            "source_family_id": [item.source_family_id for item in self.source_attestations],
        }.items():
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name} in intake batch")
        review_keys = [(item.asset_id, item.reviewer_id) for item in self.reviews]
        if len(review_keys) != len(set(review_keys)):
            raise ValueError("a reviewer may submit at most one review per asset")
        adjudication_assets = [item.asset_id for item in self.adjudications]
        if len(adjudication_assets) != len(set(adjudication_assets)):
            raise ValueError("an asset may have at most one adjudication")
        asset_ids = {item.asset_id for item in self.assets}
        if any(item.asset_id not in asset_ids for item in self.reviews):
            raise ValueError("review references an asset outside the intake batch")
        if any(item.asset_id not in asset_ids for item in self.adjudications):
            raise ValueError("adjudication references an asset outside the intake batch")
        return self
