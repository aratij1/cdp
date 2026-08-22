from __future__ import annotations

from dataclasses import dataclass

from packages.reference_enrichment.contracts import ReferenceLookupRequest, ReferenceResolution
from packages.reference_enrichment.decision_engine import decide, pending, resolve
from packages.reference_enrichment.providers import ReferenceProvider


@dataclass
class ReferenceMatchingService:
    providers: list[ReferenceProvider]

    def match(
        self, request: ReferenceLookupRequest, *, raw_value: str | None,
        normalized_value: str | None,
    ) -> ReferenceResolution:
        records = []
        test_only = False
        errors: list[str] = []
        for provider in self.providers:
            try:
                records.extend(provider.lookup(request))
                test_only = test_only or provider.test_only
            except Exception as exc:  # connector failures must become abstentions
                errors.append(f"{provider.name}:{type(exc).__name__}")
        decision = (
            pending(request, ";".join(errors), decision="REFERENCE_PROVIDER_ERROR")
            if errors else decide(request, records, test_only=test_only)
        )
        return resolve(request, decision, raw_value=raw_value, normalized_value=normalized_value)
