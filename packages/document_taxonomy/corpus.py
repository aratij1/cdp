"""Dataset representation contracts used before any router technology evaluation."""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from pydantic import Field, model_validator

from packages.domain.common import DomainModel
from .taxonomy import DocumentClass, DocumentTaxonomyV1


class CorpusRecord(DomainModel):
    document_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: DocumentClass
    parent_path: tuple[DocumentClass, ...]
    source_id: str
    source_family: str
    organization_id: str
    acquisition_channel: str
    renderer_family: str
    layout_family: str
    template_family: str
    document_origin_type: str
    degradation_family: str
    perceptual_hash: str | None = None
    contains_phi: bool = False
    adjudication_status: str = "SME_VERIFIED"

    @model_validator(mode="after")
    def valid_taxonomy_path(self):
        DocumentTaxonomyV1.validate_label(self.label, self.parent_path)
        return self


class RoutingCorpusManifest(DomainModel):
    corpus_id: str
    taxonomy_version: str = DocumentTaxonomyV1.version
    records: tuple[CorpusRecord, ...]
    minimum_sources_per_leaf: int = Field(default=3, ge=2)

    def dataset_hash(self) -> str:
        rows = sorted((record.model_dump(mode="json") for record in self.records),
                      key=lambda row: (row["document_id"], row["content_sha256"]))
        return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def representation_gaps(self) -> dict[str, list[str]]:
        leaves = {node.code for node in DocumentTaxonomyV1.nodes() if node.is_leaf}
        sources = {leaf: set() for leaf in leaves}
        for record in self.records:
            if record.label in sources:
                sources[record.label].add(record.source_id)
        return {leaf.value: sorted(values) for leaf, values in sources.items()
                if len(values) < self.minimum_sources_per_leaf}

    def quality_failures(self) -> dict[str, list[str]]:
        failures: dict[str, list[str]] = {}
        duplicate_hashes = {value for value, count in Counter(r.content_sha256 for r in self.records).items() if count > 1}
        for record in self.records:
            reasons = []
            if record.contains_phi:
                reasons.append("PHI_PRESENT")
            if record.content_sha256 in duplicate_hashes:
                reasons.append("DUPLICATE_SHA256")
            if not all((record.source_family, record.renderer_family, record.layout_family,
                        record.document_origin_type, record.degradation_family)):
                reasons.append("SOURCE_LINEAGE_INCOMPLETE")
            if reasons:
                failures[record.document_id] = reasons
        return failures

    def split_leakage(self, split_by_document: dict[str, str]) -> list[str]:
        groups: dict[tuple[str, str, str], set[str]] = {}
        for record in self.records:
            split = split_by_document.get(record.document_id)
            if split:
                groups.setdefault((record.source_family, record.renderer_family, record.template_family), set()).add(split)
        return sorted("/".join(group) for group, splits in groups.items() if len(splits) > 1)

    def class_counts(self) -> dict[str, int]:
        return dict(Counter(record.label.value for record in self.records))
