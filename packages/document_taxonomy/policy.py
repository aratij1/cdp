"""Processing equivalence and routing-risk policy for taxonomy V1."""
from packages.domain.common import DomainModel
from packages.processing_routes.contracts import ProcessingRoute
from .taxonomy import DocumentClass


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
    verification_status: str | None = None
    verified_family: DocumentClass | None = None
    expected_route: ProcessingRoute | None = None

    @property
    def processing_route_correct(self) -> bool:
        return self.authorized_route == (self.expected_route or ROUTE_BY_CLASS[self.truth])

    @property
    def false_standard_authorization(self) -> bool:
        fixed = {ProcessingRoute.CMS_FIXED_TEMPLATE, ProcessingRoute.UB_FIXED_TEMPLATE}
        return self.authorized_route in fixed and ROUTE_BY_CLASS[self.truth] not in fixed

    @property
    def unverified_fixed_authorization(self) -> bool:
        expected = {
            ProcessingRoute.CMS_STANDARD_EXTRACTOR: DocumentClass.CMS1500,
            ProcessingRoute.UB_STANDARD_EXTRACTOR: DocumentClass.UB04,
        }.get(self.authorized_route)
        return expected is not None and not (
            self.verification_status == "VERIFIED" and self.verified_family == expected)

    @property
    def safe_standard_fallback(self) -> bool:
        return (self.truth in {DocumentClass.CMS1500, DocumentClass.UB04}
                and self.prediction == self.truth
                and self.authorized_route in {ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR,
                                              ProcessingRoute.SAFE_UNKNOWN}
                and self.verification_status != "VERIFIED")

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
                "false_standard_authorization_rate": 0.0, "cms_false_authorization_rate": 0.0,
                "ub_false_authorization_rate": 0.0, "standard_to_standard_misroute_rate": 0.0,
                "cms_to_ub_authorization_rate": 0.0, "ub_to_cms_authorization_rate": 0.0,
                "unverified_fixed_authorization_rate": 0.0, "safe_standard_fallback_rate": 0.0,
                "cms_safe_fallback_rate": 0.0, "ub_safe_fallback_rate": 0.0,
                "abstention_rate": 0.0,
                "accuracy_among_non_abstained": 0.0, "mean_routing_risk_score": 0.0}
    non_abstained = [item for item in outcomes if not item.abstained]
    fixed = {ProcessingRoute.CMS_STANDARD_EXTRACTOR, ProcessingRoute.UB_STANDARD_EXTRACTOR}
    non_standard = [item for item in outcomes if ROUTE_BY_CLASS[item.truth] not in fixed]
    true_standard = [item for item in outcomes if ROUTE_BY_CLASS[item.truth] in fixed]
    cms = [item for item in outcomes if item.truth == DocumentClass.CMS1500]
    ub = [item for item in outcomes if item.truth == DocumentClass.UB04]
    ratio = lambda count, total: count / total if total else 0.0
    return {
        "exact_subtype_accuracy": ratio(sum(x.truth == x.prediction for x in outcomes), len(outcomes)),
        "processing_route_accuracy": ratio(sum(x.processing_route_correct for x in outcomes), len(outcomes)),
        "false_standard_authorization_rate": ratio(sum(x.false_standard_authorization for x in non_standard), len(non_standard)),
        "cms_false_authorization_rate": ratio(sum(x.authorized_route == ProcessingRoute.CMS_STANDARD_EXTRACTOR
                                                   for x in non_standard), len(non_standard)),
        "ub_false_authorization_rate": ratio(sum(x.authorized_route == ProcessingRoute.UB_STANDARD_EXTRACTOR
                                                  for x in non_standard), len(non_standard)),
        "standard_to_standard_misroute_rate": ratio(sum(
            x.authorized_route in fixed and x.authorized_route != ROUTE_BY_CLASS[x.truth] for x in true_standard),
            len(true_standard)),
        "cms_to_ub_authorization_rate": ratio(sum(x.authorized_route == ProcessingRoute.UB_STANDARD_EXTRACTOR
                                                   for x in cms), len(cms)),
        "ub_to_cms_authorization_rate": ratio(sum(x.authorized_route == ProcessingRoute.CMS_STANDARD_EXTRACTOR
                                                   for x in ub), len(ub)),
        "unverified_fixed_authorization_rate": ratio(sum(x.unverified_fixed_authorization for x in outcomes),
                                                       len(outcomes)),
        "safe_standard_fallback_rate": ratio(sum(x.safe_standard_fallback for x in true_standard),
                                               len(true_standard)),
        "cms_safe_fallback_rate": ratio(sum(x.safe_standard_fallback for x in cms), len(cms)),
        "ub_safe_fallback_rate": ratio(sum(x.safe_standard_fallback for x in ub), len(ub)),
        "abstention_rate": ratio(sum(x.abstained for x in outcomes), len(outcomes)),
        "accuracy_among_non_abstained": ratio(sum(x.truth == x.prediction for x in non_abstained), len(non_abstained)),
        "mean_routing_risk_score": sum(x.risk_score for x in outcomes) / len(outcomes),
    }
