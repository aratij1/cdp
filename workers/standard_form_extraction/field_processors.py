"""Field normalization, dispatched by `FieldRegion.field_type`.

Each processor takes raw OCR text and returns `(normalized_value, ok)`;
`ok=False` doesn't mean "reject the field" -- it means "normalization
couldn't make sense of this raw text", which the validation worker (Phase
3) treats as an ordinary validation failure, not a crash. Processors are
deliberately permissive parsers, not validators -- e.g. `normalize_npi`
accepts any 10-digit string; the Luhn checksum lives in
`packages.validation_rules` (Phase 3), not here, because "is this
syntactically a date/NPI/amount" and "is this NPI actually valid" are
different concerns evaluated by different pipeline stages.
"""

from __future__ import annotations

from packages.field_normalization import (
    normalize,
    normalize_checkbox,
    normalize_code,
    normalize_currency,
    normalize_date,
    normalize_npi,
    normalize_tax_id,
    normalize_text,
)

__all__ = [
    "normalize", "normalize_checkbox", "normalize_code", "normalize_currency",
    "normalize_date", "normalize_npi", "normalize_tax_id", "normalize_text",
]
