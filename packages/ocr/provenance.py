"""Canonical observation lineage carried by OCR and persisted field evidence."""

from __future__ import annotations

from datetime import datetime

from packages.domain.common import BoundingBox, DomainModel


class EvidenceProvenance(DomainModel):
    """The pixel/decision lineage needed to assess evidence dependence.

    Every field is optional so records written before Phase 8.8C remain
    readable.  Absence is meaningful: dependency analysis returns UNKNOWN.
    """

    page_sha256: str | None = None
    document_sha256: str | None = None
    source_representation_id: str | None = None
    observation_id: str | None = None
    crop_sha256: str | None = None
    crop_object_uri: str | None = None
    localization_id: str | None = None
    localization_region_id: str | None = None
    localization_method: str | None = None
    localization_version: str | None = None
    registration_transform_id: str | None = None
    preprocessing_profile: str | None = None
    preprocessing_sha256: str | None = None
    preprocessing_version: str | None = None
    engine_family: str | None = None
    engine_name: str | None = None
    engine_version: str | None = None
    model_family: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    parent_candidate_id: str | None = None
    source_candidate_id: str | None = None
    invocation_id: str | None = None
    upstream_candidate_ids: tuple[str, ...] = ()
    shared_dependency_ids: tuple[str, ...] = ()
    normalization_version: str | None = None
    bbox: BoundingBox | None = None
    produced_at: datetime | None = None
