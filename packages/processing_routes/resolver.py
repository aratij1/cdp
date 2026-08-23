"""The route-to-extractor firewall. This is the only fixed-route mapping."""
from packages.document_taxonomy.contracts import DocumentClassification
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.standard_form_verification.contracts import StandardFormStatus, StandardFormVerification
from .contracts import ProcessingRoute, ProcessingRouteDecision


class ProcessingRouteResolver:
    policy_version = "processing-route-policy-v1"

    def resolve(self, classification: DocumentClassification,
                verification: StandardFormVerification | None = None) -> ProcessingRouteDecision:
        if classification.top_level_class == DocumentClass.NON_CLAIM:
            return self._decision(ProcessingRoute.STOP_NON_CLAIM, "TOP_LEVEL_NON_CLAIM")
        if verification is not None and verification.status == StandardFormStatus.VERIFIED:
            if not verification.eligible_for_fixed_extractor:
                raise ValueError("VERIFIED evidence must explicitly authorize the fixed extractor")
            route = (ProcessingRoute.CMS_STANDARD_EXTRACTOR
                     if verification.candidate_family == DocumentClass.CMS1500
                     else ProcessingRoute.UB_STANDARD_EXTRACTOR)
            return self._decision(route, "STANDARD_FORM_VERIFIED")
        if classification.structured:
            return self._decision(ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR,
                                  "STRUCTURED_WITHOUT_STANDARD_VERIFICATION")
        if classification.claim_related:
            return self._decision(ProcessingRoute.UNSTRUCTURED_EXTRACTOR, "UNSTRUCTURED_CLAIM_RELATED")
        return self._decision(ProcessingRoute.SAFE_UNKNOWN, "INSUFFICIENT_SAFE_ROUTE_EVIDENCE")

    def _decision(self, route: ProcessingRoute, reason: str) -> ProcessingRouteDecision:
        return ProcessingRouteDecision(route=route, reason_codes=(reason,), policy_version=self.policy_version)
