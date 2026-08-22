"""Processing equivalence and routing-risk policy for taxonomy V1."""
from enum import StrEnum

from packages.domain.common import DomainModel
from .taxonomy import DocumentClass


class ProcessingRoute(StrEnum):
    CMS_FIXED_TEMPLATE = "CMS_FIXED_TEMPLATE_EXTRACTOR"
    UB_FIXED_TEMPLATE = "UB_FIXED_TEMPLATE_EXTRACTOR"
    LAYOUT_STRUCTURED = "LAYOUT_STRUCTURED_EXTRACTOR"
    LAYOUT_UNSTRUCTURED = "LAYOUT_UNSTRUCTURED_EXTRACTOR"
    NON_CLAIM_STOP = "NON_CLAIM_STOP"
    SAFE_UNKNOWN = "SAFE_UNKNOWN"


ROUTE_BY_CLASS = {
    DocumentClass.CMS1500: ProcessingRoute.CMS_FIXED_TEMPLATE,
    DocumentClass.UB04: ProcessingRoute.UB_FIXED_TEMPLATE,
    DocumentClass.CUSTOM_PROFESSIONAL: ProcessingRoute.LAYOUT_STRUCTURED,
    DocumentClass.CUSTOM_INSTITUTIONAL: ProcessingRoute.LAYOUT_STRUCTURED,
    DocumentClass.OTHER_STRUCTURED_CLAIM: ProcessingRoute.LAYOUT_STRUCTURED,
    DocumentClass.EOB: ProcessingRoute.LAYOUT_STRUCTURED,
    DocumentClass.ITEMIZED_BILL: ProcessingRoute.LAYOUT_STRUCTURED,
    DocumentClass.MEDICAL_INVOICE: ProcessingRoute.LAYOUT_STRUCTURED,
    DocumentClass.LAB_REPORT: ProcessingRoute.LAYOUT_STRUCTURED,
    DocumentClass.CLINICAL_NOTE: ProcessingRoute.LAYOUT_UNSTRUCTURED,
    DocumentClass.CORRESPONDENCE: ProcessingRoute.LAYOUT_UNSTRUCTURED,
    DocumentClass.OTHER_ATTACHMENT: ProcessingRoute.LAYOUT_UNSTRUCTURED,
    DocumentClass.COVER_PAGE: ProcessingRoute.NON_CLAIM_STOP,
    DocumentClass.DOCUMENT_SEPARATOR: ProcessingRoute.NON_CLAIM_STOP,
    DocumentClass.ADMINISTRATIVE: ProcessingRoute.NON_CLAIM_STOP,
    DocumentClass.BLANK_OR_NEAR_BLANK: ProcessingRoute.NON_CLAIM_STOP,
    DocumentClass.OTHER_NON_CLAIM: ProcessingRoute.NON_CLAIM_STOP,
    DocumentClass.UNKNOWN: ProcessingRoute.SAFE_UNKNOWN,
}


class RoutingOutcome(DomainModel):
    truth: DocumentClass
    prediction: DocumentClass
    authorized_route: ProcessingRoute
    abstained: bool = False

    @property
    def processing_route_correct(self) -> bool:
        return self.authorized_route == ROUTE_BY_CLASS[self.truth]

    @property
    def false_standard_authorization(self) -> bool:
        fixed = {ProcessingRoute.CMS_FIXED_TEMPLATE, ProcessingRoute.UB_FIXED_TEMPLATE}
        return self.authorized_route in fixed and ROUTE_BY_CLASS[self.truth] not in fixed

    @property
    def risk_score(self) -> int:
        if self.false_standard_authorization:
            return 100
        if self.truth == DocumentClass.CMS1500 and self.authorized_route == ProcessingRoute.UB_FIXED_TEMPLATE:
            return 80
        if self.truth == DocumentClass.UB04 and self.authorized_route == ProcessingRoute.CMS_FIXED_TEMPLATE:
            return 80
        if not self.processing_route_correct:
            return 40
        return 0 if self.truth == self.prediction else 5


def summarize_outcomes(outcomes: tuple[RoutingOutcome, ...]) -> dict[str, float]:
    if not outcomes:
        return {"exact_subtype_accuracy": 0.0, "processing_route_accuracy": 0.0,
                "false_standard_authorization_rate": 0.0, "abstention_rate": 0.0,
                "accuracy_among_non_abstained": 0.0, "mean_routing_risk_score": 0.0}
    non_abstained = [item for item in outcomes if not item.abstained]
    ratio = lambda count, total: count / total if total else 0.0
    return {
        "exact_subtype_accuracy": ratio(sum(x.truth == x.prediction for x in outcomes), len(outcomes)),
        "processing_route_accuracy": ratio(sum(x.processing_route_correct for x in outcomes), len(outcomes)),
        "false_standard_authorization_rate": ratio(sum(x.false_standard_authorization for x in outcomes), len(outcomes)),
        "abstention_rate": ratio(sum(x.abstained for x in outcomes), len(outcomes)),
        "accuracy_among_non_abstained": ratio(sum(x.truth == x.prediction for x in non_abstained), len(non_abstained)),
        "mean_routing_risk_score": sum(x.risk_score for x in outcomes) / len(outcomes),
    }
