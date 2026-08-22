"""ICD-10-CM diagnosis code validation: syntax always checked; a full
code-set *reference* lookup (does this code actually exist in the current
ICD-10-CM release) is a separate, optional adapter -- CMS republishes the
code set yearly and bundling/maintaining it is out of scope here. Verified
against real diagnosis codes from the supplied dataset (G31.84, F02.81,
F20.9 -- see docs/DATASET_FINDINGS.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

# Category: 1 letter (not 'U', reserved by WHO) + 2 alphanumerics, then an
# optional decimal point + 1-4 alphanumerics (the subcategory/extension).
# X12.345 and the compact electronic-claim representation X12345 are
# equivalent syntax. Requiring the display-only decimal incorrectly rejected
# valid compact values such as Z0000.
_ICD10_PATTERN = re.compile(r"^[A-TV-Z][0-9A-Z][0-9A-Z](?:\.?[0-9A-Z]{1,4})?$")


def is_valid_icd10_syntax(code: str) -> bool:
    return bool(_ICD10_PATTERN.match(code.strip().upper()))


@dataclass(frozen=True)
class CodeReferenceResult:
    known: bool
    description: str | None = None


class Icd10ReferenceAdapter(Protocol):
    def lookup(self, code: str) -> CodeReferenceResult: ...


class NoOpIcd10ReferenceAdapter:
    """Default adapter: syntax-only validation, no code-set lookup. Wiring
    a real ICD-10-CM table is a config/data change (load a code list into
    an adapter implementing `Icd10ReferenceAdapter`), not a code change
    here or in the validation engine that calls it."""

    def lookup(self, code: str) -> CodeReferenceResult:
        return CodeReferenceResult(known=False, description=None)
