"""Runtime-neutral template-lineage compatibility evidence contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TemplateCompatibilityStatus(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    PARTIALLY_COMPATIBLE = "PARTIALLY_COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class TemplateCompatibilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = "template-compatibility-v1"
    family: str | None = None
    family_compatibility: float = Field(ge=0, le=1)
    aspect_ratio_similarity: float = Field(ge=0, le=1)
    line_structure_similarity: float = Field(ge=0, le=1)
    edge_projection_similarity: float = Field(ge=0, le=1)
    anchor_visibility: float = Field(ge=0, le=1)
    normalized_layout_similarity: float = Field(ge=0, le=1)
    form_fingerprint_similarity: float = Field(ge=0, le=1)
    compatibility_score: float = Field(ge=0, le=1)
    status: TemplateCompatibilityStatus
    reason_codes: tuple[str, ...] = ()
