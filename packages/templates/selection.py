"""Fail-closed form/template selection shared by validation and output."""

from packages.domain.enums import BundleType, ClaimFormType
from packages.templates.models import Template
from packages.templates.registry import TemplateRegistry


def form_type_from_template_lineage(lineage: str | None) -> ClaimFormType:
    template_id = (lineage or "").split("@", 1)[0].strip().casefold()
    if template_id == "cms1500":
        return ClaimFormType.CMS1500
    if template_id == "ub04":
        return ClaimFormType.UB04
    raise ValueError(f"UNSUPPORTED_OR_MISSING_TEMPLATE_LINEAGE:{lineage!r}")


def form_type_from_output_context(
    explicit: str | None, bundle_type: BundleType | None
) -> ClaimFormType:
    if explicit is not None:
        form_type = ClaimFormType(explicit)
        if form_type not in {ClaimFormType.CMS1500, ClaimFormType.UB04}:
            raise ValueError(f"OUTPUT_REQUIRES_STANDARD_FORM_TYPE:{form_type.value}")
        return form_type
    if bundle_type in {BundleType.A_CMS1500_SINGLE, BundleType.B_CMS1500_BUNDLE}:
        return ClaimFormType.CMS1500
    if bundle_type == BundleType.C_UB_SINGLE:
        return ClaimFormType.UB04
    raise ValueError("OUTPUT_STANDARD_FORM_TYPE_UNAVAILABLE")


def exact_family_template(
    registry: TemplateRegistry, form_type: ClaimFormType
) -> Template:
    """Select within the requested family or propagate TemplateNotFoundError."""
    return registry.latest_for_form_type(form_type)
