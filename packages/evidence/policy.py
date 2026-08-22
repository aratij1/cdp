from __future__ import annotations

from pathlib import Path

import yaml

from packages.criticality import CriticalityLevel
from packages.evidence.models import EvidenceBundle, EvidenceClass

DEFAULT_EVIDENCE_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "evidence_policies.yaml"


class EvidencePolicy:
    def __init__(self, payload: dict) -> None:
        self.version = str(payload["version"])
        self._fields = payload.get("fields", {})
        self._defaults = payload.get("defaults", {})

    @classmethod
    def load(cls, path: str | Path = DEFAULT_EVIDENCE_POLICY_PATH) -> "EvidencePolicy":
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def requirements(self, field_name: str, criticality: CriticalityLevel) -> tuple[frozenset[EvidenceClass], ...]:
        spec = self._fields.get(field_name) or self._defaults.get(criticality.value) or {}
        return tuple(frozenset(EvidenceClass(item) for item in option) for option in spec.get("accept_any", []))

    def evaluate(self, field_name: str, criticality: CriticalityLevel,
                 bundle: EvidenceBundle) -> tuple[bool, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        options = self.requirements(field_name, criticality)
        available = bundle.available_classes
        if any(option <= available for option in options):
            return True, tuple(sorted(item.value for item in available)), (), ()
        if not options:
            return False, tuple(sorted(item.value for item in available)), (), ("MISSING_FIELD_EVIDENCE_POLICY",)
        closest = min(options, key=lambda option: (len(option - available), len(option)))
        missing = tuple(sorted(item.value for item in closest - available))
        reasons = tuple(f"MISSING_{item}_{_LABELS[item]}" for item in missing)
        return False, tuple(sorted(item.value for item in available)), missing, reasons


_LABELS = {
    "E1": "EXTRACTION_EVIDENCE", "E2": "INDEPENDENT_CONFIRMATION",
    "E3": "REGISTRATION_EVIDENCE", "E4": "DETERMINISTIC_VALIDATION",
    "E5": "REFERENCE_CONFIRMATION", "E6": "CROSS_FIELD_CONFIRMATION",
    "E7": "INDEPENDENT_AI_CONFIRMATION", "E8": "HUMAN_VERIFICATION",
}
