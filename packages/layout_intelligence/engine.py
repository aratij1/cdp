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


def _bbox_key(bbox) -> tuple:
    return (round(bbox.x0, 1), round(bbox.y0, 1), round(bbox.x1, 1), round(bbox.y1, 1))


def _weaker_field(
    name_a: str, candidate_a: CanonicalLayoutCandidate,
    name_b: str, candidate_b: CanonicalLayoutCandidate,
) -> str:
    """Which of two fields whose top candidates collide on the same bbox
    should yield, decided by evidence strength (never by name/order alone)
    so a genuine tie falls back to a deterministic but arbitrary-looking
    choice only as a last resort."""
    if candidate_a.confidence != candidate_b.confidence:
        return name_a if candidate_a.confidence < candidate_b.confidence else name_b
    if candidate_a.mapping_confidence != candidate_b.mapping_confidence:
        return name_a if candidate_a.mapping_confidence < candidate_b.mapping_confidence else name_b
    return max(name_a, name_b)


def _resolve_bbox_conflicts(candidates: dict[str, list[CanonicalLayoutCandidate]]) -> None:
    """Two different fields should not both claim the same bounding box as
    their best evidence -- that is a sign one field's label match landed on
    the wrong line, not that the fields legitimately share a value. Resolve
    by confidence: the weaker field loses only that one conflicting
    candidate (falling back to its own next-best, distinct-bbox evidence if
    it has any), never the whole field wholesale. A field that legitimately
    has the strongest evidence for a bbox keeps it untouched."""
    changed = True
    while changed:
        changed = False
        claimed: dict[tuple, str] = {}
        for field_name, values in candidates.items():
            if not values:
                continue
            key = _bbox_key(values[0].bbox)
            holder = claimed.get(key)
            if holder is None:
                claimed[key] = field_name
                continue
            loser = _weaker_field(field_name, values[0], holder, candidates[holder][0])
            candidates[loser].pop(0)
            if not candidates[loser]:
                del candidates[loser]
            changed = True
            break


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
        _resolve_bbox_conflicts(candidates)
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
