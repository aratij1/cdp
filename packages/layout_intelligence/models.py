from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from packages.domain.common import BoundingBox, DomainModel


class RegionType(StrEnum):
    HEADER = "HEADER"
    LABEL_VALUE = "LABEL_VALUE"
    PARAGRAPH = "PARAGRAPH"
    TABLE = "TABLE"
    CHECKBOX_GROUP = "CHECKBOX_GROUP"
    ADDRESS_BLOCK = "ADDRESS_BLOCK"
    IDENTIFIER_BLOCK = "IDENTIFIER_BLOCK"
    FOOTER = "FOOTER"
    UNKNOWN = "UNKNOWN"


class GenericRoute(StrEnum):
    KNOWN_STANDARD = "KNOWN_STANDARD"
    UNKNOWN_STRUCTURED = "UNKNOWN_STRUCTURED"
    UNKNOWN_UNSTRUCTURED = "UNKNOWN_UNSTRUCTURED"
    NON_CLAIM = "NON_CLAIM"


class LayoutToken(DomainModel):
    text: str
    normalized_text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    bbox: BoundingBox
    page_number: int = Field(ge=1)
    engine: str
    reading_order: int | None = Field(default=None, ge=0)


class LayoutLine(DomainModel):
    tokens: list[LayoutToken]
    bbox: BoundingBox
    text: str
    reading_order: int = Field(ge=0)


class LayoutRegion(DomainModel):
    region_id: str
    region_type: RegionType
    bbox: BoundingBox
    tokens: list[LayoutToken]


class LabelMatch(DomainModel):
    field_name: str
    alias: str
    text: str
    bbox: BoundingBox
    similarity: float = Field(ge=0, le=1)
    line_index: int = Field(ge=0)


class LabelValueLinkEvidence(DomainModel):
    field_name: str
    label_text: str
    label_bbox: BoundingBox
    candidate_text: str
    candidate_bbox: BoundingBox
    horizontal_distance: float
    vertical_distance: float
    same_row: bool
    same_column: bool
    datatype_valid: bool
    label_similarity: float = Field(ge=0, le=1)
    spatial_score: float = Field(ge=0, le=1)
    semantic_score: float | None = Field(default=None, ge=0, le=1)
    total_score: float = Field(ge=0, le=1)
    relationship: str


class CanonicalLayoutCandidate(DomainModel):
    field_name: str
    value: str
    confidence: float = Field(ge=0, le=1)
    bbox: BoundingBox
    original_label: str
    matched_alias: str
    mapping_method: str = "CONFIGURED_LABEL_ALIAS"
    mapping_confidence: float = Field(ge=0, le=1)
    datatype_valid: bool
    relationship_evidence: LabelValueLinkEvidence


class SchemaEvidence(DomainModel):
    schema_family: str
    confidence: float = Field(ge=0, le=1)
    supporting_fields: list[str]
    reason_codes: list[str]
