from __future__ import annotations

from pathlib import Path

import yaml

from packages.criticality import CriticalityLevel
from packages.evidence.models import EvidenceBundle, EvidenceClass

DEFAULT_EVIDENCE_POLICY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "evidence_policies.yaml"
)


class EvidencePolicyUnavailableError(RuntimeError):
    pass


class EvidencePolicy:
    def __init__(self, payload: dict) -> None:
        self.version = str(payload["version"])
        self._fields = payload.get("fields", {})
        self._defaults = payload.get("defaults", {})

    @classmethod
    def load(cls, path: str | Path = DEFAULT_EVIDENCE_POLICY_PATH) -> EvidencePolicy:
        try:
            payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise EvidencePolicyUnavailableError(f"evidence policy unavailable: {path}") from exc
        if not isinstance(payload, dict) or "version" not in payload:
            raise EvidencePolicyUnavailableError("evidence policy is malformed")
        return cls(payload)

    def field_spec(
        self, document_family: str, field_name: str, criticality: CriticalityLevel
    ) -> tuple[str, dict]:
        qualified = f"{document_family.upper()}.{field_name}"
        spec = self._fields.get(qualified) or self._fields.get(field_name)
        if spec is not None:
            return qualified if qualified in self._fields else f"*.{field_name}", spec
        return f"default.{criticality.value}", self._defaults.get(criticality.value) or {}

    def requirements(
        self, field_name: str, criticality: CriticalityLevel, document_family: str = "*"
    ) -> tuple[frozenset[EvidenceClass], ...]:
        _, spec = self.field_spec(document_family, field_name, criticality)
        return tuple(
            frozenset(EvidenceClass(item) for item in option)
            for option in spec.get("accept_any", [])
        )

    def reachability_disposition(
        self,
        field_name: str,
        criticality: CriticalityLevel,
        document_family: str = "*",
    ) -> str | None:
        _, spec = self.field_spec(document_family, field_name, criticality)
        value = spec.get("reachability")
        return str(value) if value is not None else None

    def evaluate(
        self,
        field_name: str,
        criticality: CriticalityLevel,
        bundle: EvidenceBundle,
        document_family: str = "*",
        reference_authorized: bool = False,
    ) -> tuple[bool, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        _, spec = self.field_spec(document_family, field_name, criticality)
        options = self.requirements(field_name, criticality, document_family)
        available = self._qualified_available(bundle, criticality, spec)
        if any(option <= available for option in options):
            return True, tuple(sorted(item.value for item in available)), (), ()
        if not options:
            return (
                False,
                tuple(sorted(item.value for item in available)),
                (),
                ("MISSING_FIELD_EVIDENCE_POLICY",),
            )
        eligible = (
            tuple(
                option
                for option in options
                if EvidenceClass.E5 not in option
                or EvidenceClass.E5 in available
                or reference_authorized
            )
            or options
        )
        closest = min(eligible, key=lambda option: (len(option - available), len(option)))
        missing = tuple(sorted(item.value for item in closest - available))
        reasons = tuple(f"MISSING_{item}_{_LABELS[item]}" for item in missing)
        return False, tuple(sorted(item.value for item in available)), missing, reasons

    @staticmethod
    def _qualified_available(
        bundle: EvidenceBundle, criticality: CriticalityLevel, spec: dict | None = None
    ) -> set[EvidenceClass]:
        """Return policy-eligible classes, excluding merely plausible support."""
        critical = criticality in {CriticalityLevel.C2, CriticalityLevel.C3}
        spec = spec or {}
        field_specific_e3 = critical or bool(spec.get("require_field_specific_e3"))
        strong_e4 = critical or bool(spec.get("require_strong_e4"))
        allowed_e6 = set(spec.get("allowed_e6_types") or ())
        available: set[EvidenceClass] = set()
        for item in bundle.evidence_items:
            if item.evidence_class == EvidenceClass.E0:
                continue
            if item.evidence_class == EvidenceClass.E2 and not (
                item.independent
                and item.evidence_type == "OCR_AGREEMENT_INDEPENDENT"
            ):
                continue
            if field_specific_e3 and item.evidence_class == EvidenceClass.E3 and not item.metadata.get(
                "field_specific", False
            ):
                continue
            if strong_e4 and item.evidence_class == EvidenceClass.E4 and item.metadata.get(
                "strength"
            ) != "STRONG":
                continue
            if item.evidence_class == EvidenceClass.E6 and (
                allowed_e6 and item.evidence_type not in allowed_e6
            ):
                continue
            available.add(item.evidence_class)
        return available


_LABELS = {
    "E1": "EXTRACTION_EVIDENCE",
    "E2": "INDEPENDENT_CONFIRMATION",
    "E3": "REGISTRATION_EVIDENCE",
    "E4": "DETERMINISTIC_VALIDATION",
    "E5": "REFERENCE_CONFIRMATION",
    "E6": "CROSS_FIELD_CONFIRMATION",
    "E7": "INDEPENDENT_AI_CONFIRMATION",
    "E8": "HUMAN_VERIFICATION",
}
