"""Exact source/processor-page linkage. Page identity never establishes claim boundaries."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum


class BindingState(StrEnum):
    EXACT = "EXACT"
    AMBIGUOUS = "AMBIGUOUS"
    UNBOUND = "UNBOUND"


@dataclass(frozen=True)
class PageIdentity:
    page_id: str
    source_asset_sha256: str
    source_page_index: int
    rendered_page_sha256: str
    package_id: str
    provenance: tuple[str, ...]
    claim_id: str | None = None
    claim_boundary_provenance: str | None = None

    def __post_init__(self):
        if (
            not self.page_id
            or not self.package_id
            or not self.provenance
            or type(self.source_page_index) is not int
            or self.source_page_index < 0
            or any(
                not re.fullmatch(r"[a-f0-9]{64}", x)
                for x in (self.source_asset_sha256, self.rendered_page_sha256)
            )
            or bool(self.claim_id) != bool(self.claim_boundary_provenance)
        ):
            raise ValueError("INCOMPLETE_PAGE_LINEAGE")

    @property
    def key(self) -> tuple[str, int, str, str]:
        return (
            self.source_asset_sha256,
            self.source_page_index,
            self.rendered_page_sha256,
            self.package_id,
        )


@dataclass(frozen=True)
class SourcePageBinding:
    source_page_id: str
    source_asset_sha256: str
    source_page_index: int
    rendered_page_sha256: str
    package_id: str
    cdp_page_id: str | None
    cdp_page_sha256: str | None
    claim_id: str | None
    state: BindingState
    binding_method: str
    binding_confidence: float | None
    binding_version: str
    provenance: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


def bind_pages(
    sources: tuple[PageIdentity, ...], pages: tuple[PageIdentity, ...]
) -> tuple[SourcePageBinding, ...]:
    if len({s.page_id for s in sources}) != len(sources):
        raise ValueError("DUPLICATE_SOURCE_PAGE")
    ids: dict[str, set[tuple]] = {}
    index: dict[tuple, list[PageIdentity]] = {}
    for page in pages:
        ids.setdefault(page.page_id, set()).add(
            (*page.key, page.claim_id, page.claim_boundary_provenance)
        )
        index.setdefault(page.key, []).append(page)
    result = []
    for source in sources:
        matches = index.get(source.key, [])
        unique = {p.page_id: p for p in matches}
        contradictory = any(len(ids[p.page_id]) != 1 for p in matches)
        state = (
            BindingState.AMBIGUOUS
            if len(unique) > 1 or contradictory
            else BindingState.EXACT
            if unique
            else BindingState.UNBOUND
        )
        selected = next(iter(unique.values())) if state == BindingState.EXACT else None
        result.append(
            SourcePageBinding(
                source.page_id,
                source.source_asset_sha256,
                source.source_page_index,
                source.rendered_page_sha256,
                source.package_id,
                selected.page_id if selected else None,
                selected.rendered_page_sha256 if selected else None,
                selected.claim_id if selected else None,
                state,
                "ASSET_HASH_FRAME_RENDERED_HASH_PACKAGE_EXACT",
                1.0 if selected else None,
                "source-page-binding-v1",
                source.provenance + (selected.provenance if selected else ()),
            )
        )
    return tuple(result)


def complete_claims(
    bindings: tuple[SourcePageBinding, ...], claim_pages: dict[str, frozenset[str]]
) -> frozenset[str]:
    """Use externally established complete claim membership; never drop a bad page."""
    exact = {b.cdp_page_id: b for b in bindings if b.state == BindingState.EXACT}
    return frozenset(
        claim
        for claim, pages in claim_pages.items()
        if pages and all(p in exact and exact[p].claim_id == claim for p in pages)
    )
