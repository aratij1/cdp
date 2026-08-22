"""Router input: everything the hybrid model router needs to decide the
next extraction stage for one field. Assumes template rules + OpenCV
alignment + regional PaddleOCR (escalation steps 1-4 in
docs/ARCHITECTURE.md §9) have already been attempted by the standard
extraction path -- the router's job starts at "this field still isn't
good enough, what next."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.domain.enums import ExtractionMethod, FieldCriticality


@dataclass(frozen=True)
class RouterInput:
    field_name: str
    field_criticality: FieldCriticality
    ocr_confidence: float
    validation_failed: bool = False
    ocr_disagreement: bool = False
    cache_hit: bool = False
    is_table_field: bool = False
    is_unstructured_document: bool = False
    vlm_enabled: bool = True
    evidence_policy_satisfied: bool = False
    attempted_methods: frozenset[ExtractionMethod] = field(default_factory=frozenset)
