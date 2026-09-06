"""Stage-aware engineering blocker ownership. Never a production acceptance gate."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from packages.field_localization.scoring import type_compatibility

from .models import Candidate
from .normalization import comparison_key, normalize
from .provenance import complete

if TYPE_CHECKING:
    from .pipeline import LegacyFieldResult


@dataclass(frozen=True)
class SourceCondition:
    field_name: str
    source_sha256: str
    kind: str
    inspection_id: str
    pixel_region: tuple[float, float, float, float]
    authority: str = field(default="ENGINEERING_PIXEL_INSPECTION", init=False)
    release_truth: bool = field(default=False, init=False)


@dataclass(frozen=True)
class BlockerAssessment:
    field_name: str
    technical: tuple[str, ...]
    external: tuple[str, ...]
    reclassified: tuple[str, ...] = ()
    resolved: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    document_candidate_id: str | None = None
    document_value: str | None = None
    production_authority: bool = field(default=False, init=False)


def assess_field(
    legacy: LegacyFieldResult,
    discoveries: list[Candidate],
    *,
    source_sha256: str,
    source_condition: SourceCondition | None = None,
    enable_recovery: bool = True,
    enable_validation: bool = True,
) -> BlockerAssessment:
    """Reconcile recorded failures with the current document evidence, without truth.

    Pixel inspection may change review ownership, never establish a canonical value.
    Candidates alone cannot establish that source text is conflicting or unreadable.
    """
    name = legacy.field_name
    technical = list(legacy.technical_blockers)
    external = list(legacy.evidence_blockers)
    if source_condition is not None:
        x0, y0, x1, y1 = source_condition.pixel_region
        if (
            source_condition.field_name != name
            or source_condition.source_sha256 != source_sha256
            or not source_condition.inspection_id
            or not all(math.isfinite(v) for v in (x0, y0, x1, y1))
            or not (0 <= x0 < x1 and 0 <= y0 < y1)
            or source_condition.kind
            not in {
                "MULTIPLE_PRINTED_VALUES",
                "SOURCE_OVERPRINT",
                "ILLEGIBLE_SOURCE_CHARACTERS",
            }
        ):
            raise ValueError("SOURCE_INSPECTION_BINDING_INVALID")
        source_failures = {
            "CANDIDATE_ASSEMBLY",
            "WRONG_CROP",
            "MISSING_CROP",
            "CANDIDATE_AMBIGUITY",
            "SOFTWARE_VALIDATION",
        }
        moved = tuple(b for b in technical if b in source_failures)
        return BlockerAssessment(
            name,
            tuple(b for b in technical if b not in source_failures),
            tuple(dict.fromkeys([*external, "SOURCE_REVIEW_REQUIRED"])),
            reclassified=moved,
            reasons=(
                "TECHNICAL_BLOCKER_RECLASSIFIED",
                source_condition.kind,
                "SOURCE_REVIEW_PRESERVED_NO_VALUE_SELECTED",
            ),
        )

    def structurally_valid(candidate: Candidate) -> bool:
        return (
            type_compatibility("ALPHANUMERIC_ID", candidate.value, name) == 1.0
            if name == "relationship"
            else normalize(name, candidate.value)[1] is True
        )

    observed = [
        c
        for c in discoveries
        if c.field_name == name
        and c.evidence
        and c.features.format_valid is True
        and structurally_valid(c)
        and all(
            e.source == "SPATIAL_EXTRACTION"
            and complete(e)
            and e.source_id == source_sha256
            and e.bbox
            and e.bbox[0] < e.bbox[2]
            and e.bbox[1] < e.bbox[3]
            for e in c.evidence
        )
    ]
    keys = {comparison_key(name, c.value) for c in observed}
    resolved: list[str] = []
    reasons: list[str] = []
    proposed = None
    # An atomic registry value with one literal source observation can satisfy
    # acquisition failures. A weak/malformed competing observation prevents this.
    if (
        enable_recovery
        and name in {"relationship", "member_id"}
        and not legacy.candidates
        and not legacy.canonical_value
        and len(keys) == 1
        and observed
        and len(observed) == len(discoveries)
    ):
        proposed = observed[0]
        resolved = [
            b for b in technical if b in {"CANDIDATE_ASSEMBLY", "MISSING_CROP", "WRONG_CROP"}
        ]
        technical = [b for b in technical if b not in resolved]
        reasons.append("UNIQUE_LITERAL_ATOMIC_DOCUMENT_RECOVERY_SHADOW_ONLY")

    # Whole-token member ID plus appended non-ID text is not a second valid ID.
    # Require the selected original ID, confirmed strong geometry and a literal
    # document observation. Do not strip the invalid alternative or promote it.
    valid_original = [c for c in legacy.candidates if structurally_valid(c)]
    if (
        enable_validation
        and name == "member_id"
        and "CANDIDATE_AMBIGUITY" in technical
        and not legacy.wrong_crop
        and not legacy.missing_crop
        and len(valid_original) == 1
        and legacy.canonical_value
        == (valid_original[0].normalized_value or valid_original[0].value)
        and 0.9 <= (valid_original[0].features.geometry_confidence or 0) <= 1
        and keys == {comparison_key(name, legacy.canonical_value)}
    ):
        technical.remove("CANDIDATE_AMBIGUITY")
        resolved.append("CANDIDATE_AMBIGUITY")
        reasons.append("INVALID_EXTRA_TEXT_ALTERNATIVE_NOT_A_SECOND_MEMBER_ID")

    return BlockerAssessment(
        name,
        tuple(technical),
        tuple(external),
        resolved=tuple(resolved),
        reasons=tuple(reasons),
        document_candidate_id=proposed.candidate_id if proposed else None,
        document_value=proposed.value if proposed else None,
    )
