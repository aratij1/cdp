"""Reference-only authority configuration. Construction performs no lookup."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .lookup_runtime import LookupPolicy


class ProviderType(StrEnum):
    MEMBER = "MEMBER"
    PROVIDER = "PROVIDER"
    IDENTITY = "IDENTITY"
    SOURCE = "SOURCE"


@dataclass(frozen=True)
class AuthorityConfiguration:
    provider_type: ProviderType
    version: str
    endpoint_reference: str | None = None
    snapshot_reference: str | None = None
    credential_reference_name: str | None = None
    timeout_ms: int = 500
    cache_ttl_seconds: float = 0
    production_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.provider_type, ProviderType) or not self.version.strip():
            raise ValueError("INVALID_PROVIDER_CONFIGURATION")
        # Opaque registry names only. Actual URLs, paths and credentials belong
        # in the host's governed registry, which this contract does not resolve.
        for reference in (
            self.endpoint_reference,
            self.snapshot_reference,
            self.credential_reference_name,
        ):
            if reference is not None and not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.-]{0,127}", reference
            ):
                raise ValueError("REFERENCE_NAME_REQUIRED_NOT_INLINE_VALUE")
        if self.endpoint_reference and self.snapshot_reference:
            raise ValueError("AMBIGUOUS_AUTHORITY_SOURCE")
        LookupPolicy(timeout_ms=self.timeout_ms, ttl_seconds=self.cache_ttl_seconds)

    @property
    def source_reference_supplied(self) -> bool:
        return bool(self.endpoint_reference or self.snapshot_reference)

    @property
    def status(self) -> str:
        # A reference cannot prove that a governed transport/snapshot exists.
        return "NOT_AVAILABLE"
