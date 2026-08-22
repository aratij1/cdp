"""Production-readiness checks for template registration assets."""

from __future__ import annotations

from collections.abc import Iterable

from packages.domain.enums import ClaimFormType
from packages.templates.canonical import CanonicalTemplateError
from packages.templates.registry import TemplateRegistry


def missing_reference_templates(
    registry: TemplateRegistry, form_types: Iterable[ClaimFormType]
) -> list[str]:
    missing: list[str] = []
    for form_type in sorted(set(form_types), key=lambda item: item.value):
        template = registry.latest_for_form_type(form_type)
        try:
            reference = registry.load_reference_image(template)
        except CanonicalTemplateError:
            reference = None
        if reference is None:
            missing.append(f"{template.template_id}@{template.version}")
    return missing


def require_reference_templates(
    registry: TemplateRegistry, form_types: Iterable[ClaimFormType]
) -> None:
    missing = missing_reference_templates(registry, form_types)
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "template reference images are required for a fresh accuracy run; "
            f"missing: {joined}. Configure non-PHI operator-approved blank references."
        )
