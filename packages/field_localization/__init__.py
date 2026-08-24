from .conflict import FieldRegionConflictDetector, RegionOwnership
from .contracts import (
    FieldDefinition,
    FieldLocationEvidence,
    FieldRelationship,
    LocalizationCandidate,
    LocalizationStage,
    PageZone,
)
from .locator import FieldLocator
from .metrics import (
    LocalizationMetricRecord,
    RegionOutcome,
    aggregate_localization,
    calibration_table,
    classify_region,
    intersection_over_union,
    production_usable,
    value_containment,
)
from .registration import TransformedRegion, transform_template_region
from .registry import FieldDefinitionRegistry
from .roi import DynamicROIResolver
from .scoring import (
    LocalizationScoringPolicy,
    LocalizationWeights,
    semantic_confidence,
    type_compatibility,
)

__all__ = [
    "DynamicROIResolver",
    "FieldDefinition",
    "FieldDefinitionRegistry",
    "FieldLocationEvidence",
    "FieldLocator",
    "FieldRegionConflictDetector",
    "FieldRelationship",
    "LocalizationCandidate",
    "LocalizationMetricRecord",
    "LocalizationScoringPolicy",
    "LocalizationStage",
    "LocalizationWeights",
    "PageZone",
    "RegionOutcome",
    "RegionOwnership",
    "TransformedRegion",
    "aggregate_localization",
    "calibration_table",
    "classify_region",
    "intersection_over_union",
    "production_usable",
    "semantic_confidence",
    "transform_template_region",
    "type_compatibility",
    "value_containment",
]
