from enum import StrEnum

from packages.domain.common import DomainModel
from .taxonomy import DocumentClass


class BundleClass(StrEnum):
    SINGLE_STANDARD_CLAIM = "SINGLE_STANDARD_CLAIM"
    STANDARD_CLAIM_WITH_ATTACHMENTS = "STANDARD_CLAIM_WITH_ATTACHMENTS"
    CUSTOM_CLAIM_WITH_ATTACHMENTS = "CUSTOM_CLAIM_WITH_ATTACHMENTS"
    SUPPORT_ONLY_BUNDLE = "SUPPORT_ONLY_BUNDLE"
    NON_CLAIM_BUNDLE = "NON_CLAIM_BUNDLE"
    MIXED_UNKNOWN = "MIXED_UNKNOWN"


class PageClassification(DomainModel):
    page_number: int
    taxonomy_class: DocumentClass


class BundleClassification(DomainModel):
    bundle_class: BundleClass
    pages: tuple[PageClassification, ...]
    context_used: bool
    page_contradiction_overridden: bool = False


def classify_bundle(pages: tuple[PageClassification, ...]) -> BundleClassification:
    labels = {page.taxonomy_class for page in pages}
    standard = labels & {DocumentClass.CMS1500, DocumentClass.UB04}
    custom = labels & {DocumentClass.CUSTOM_PROFESSIONAL, DocumentClass.CUSTOM_INSTITUTIONAL,
                       DocumentClass.OTHER_STRUCTURED_CLAIM}
    support = any(DocumentClass.CLAIM_SUPPORT in DocumentTaxonomyV1.ancestors(label) for label in labels)
    non_claim = all(DocumentClass.NON_CLAIM in DocumentTaxonomyV1.ancestors(label) for label in labels)
    if len(pages) == 1 and standard:
        result = BundleClass.SINGLE_STANDARD_CLAIM
    elif standard and support:
        result = BundleClass.STANDARD_CLAIM_WITH_ATTACHMENTS
    elif custom and support:
        result = BundleClass.CUSTOM_CLAIM_WITH_ATTACHMENTS
    elif support and not standard and not custom:
        result = BundleClass.SUPPORT_ONLY_BUNDLE
    elif non_claim:
        result = BundleClass.NON_CLAIM_BUNDLE
    else:
        result = BundleClass.MIXED_UNKNOWN
    return BundleClassification(bundle_class=result, pages=pages, context_used=len(pages) > 1)


from .taxonomy import DocumentTaxonomyV1  # avoid obscuring the page/document contract above
