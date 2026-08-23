from __future__ import annotations

from pathlib import Path

from packages.field_localization import FieldDefinitionRegistry, FieldLocationEvidence, FieldLocator
from packages.page_observation import PageObservation

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config/field_definitions/cms1500_v1.yaml"


class CMS1500FieldGraph:
    version = "cms1500-field-graph-v1"

    def __init__(self, registry: FieldDefinitionRegistry | None = None,
                 locator: FieldLocator | None = None):
        self.registry = registry or FieldDefinitionRegistry.load(DEFAULT_CONFIG)
        self.locator = locator or FieldLocator()

    def locate(self, observation: PageObservation) -> dict[str, FieldLocationEvidence]:
        return {
            definition.field_name: self.locator.locate(observation, definition)
            for definition in self.registry.for_family("CMS1500")
        }
