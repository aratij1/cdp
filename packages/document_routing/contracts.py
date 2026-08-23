from packages.domain.common import DomainModel
from packages.document_taxonomy.contracts import DocumentClassification
from packages.processing_routes.contracts import ProcessingRoute, ProcessingRouteDecision
from packages.standard_form_verification.contracts import StandardFormVerification


class DocumentRoutingDecision(DomainModel):
    classification: DocumentClassification
    standard_verification: StandardFormVerification | None = None
    processing_route: ProcessingRoute
    route_reason_codes: tuple[str, ...]
    decision_service_version: str = "document-routing-decision-v1"
    evaluation_only: bool = False


class RoutingDecisionContext(DomainModel):
    document_id: str
    page_id: str
    runtime_context: str = "runtime"
