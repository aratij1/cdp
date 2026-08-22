from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from packages.domain.common import DomainModel
from .labels import LabelMatcher
from .linker import link_values
from .models import CanonicalLayoutCandidate, GenericRoute, LayoutLine, SchemaEvidence
from .reading_order import reconstruct
from .schema import infer_schema
from .tables import TableResult, reconstruct_table

DEFAULT_LABELS = Path(__file__).resolve().parents[2] / "config" / "layout_label_aliases.yaml"


class BundleDResult(DomainModel):
    route: GenericRoute
    route_confidence: float = Field(ge=0, le=1)
    route_reason_codes: list[str]
    lines: list[LayoutLine]
    candidates: dict[str, list[CanonicalLayoutCandidate]]
    schema_evidence: SchemaEvidence
    table: TableResult
    engine: str


class BundleDLayoutEngine:
    def __init__(self, labels_path: str | Path = DEFAULT_LABELS) -> None:
        self.labels = LabelMatcher.from_yaml(labels_path)

    def extract(self, ocr_lines: list[Any], *, page_number: int,
                width: int, height: int, engine: str) -> BundleDResult:
        lines = reconstruct(ocr_lines, page_number=page_number, width=width,
                            height=height, engine=engine)
        matches = self.labels.detect(lines)
        candidates: dict[str, list[CanonicalLayoutCandidate]] = {}
        for match in matches:
            linked = link_values(match, lines, datatype=self.labels.datatype(match.field_name),
                                 vocabulary=self.labels.vocabulary())
            if linked:
                candidates.setdefault(match.field_name, []).extend(linked)
        for values in candidates.values():
            values.sort(key=lambda item: item.confidence, reverse=True)
        schema = infer_schema(set(candidates), token_count=sum(len(line.tokens) for line in lines))
        table = reconstruct_table(lines)
        if schema.schema_family == "NON_CLAIM":
            route = GenericRoute.NON_CLAIM
        elif schema.schema_family == "UNKNOWN":
            route = GenericRoute.UNKNOWN_UNSTRUCTURED
        else:
            route = GenericRoute.UNKNOWN_STRUCTURED
        return BundleDResult(
            route=route, route_confidence=schema.confidence,
            route_reason_codes=["NO_STANDARD_TEMPLATE_MATCH", *schema.reason_codes],
            lines=lines, candidates=candidates, schema_evidence=schema,
            table=table, engine=engine,
        )
