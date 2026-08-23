import pytest

from packages.document_routing.decision_service import DocumentRoutingDecisionService
from packages.document_taxonomy.contracts import DocumentClassification
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.processing_routes.contracts import ProcessingRoute
from packages.standard_form_verification.contracts import StandardFormStatus, StandardFormVerification
from packages.standard_form_verification.evidence import StandardFormEvidence


def _classification(family: DocumentClass, *, structured=True):
    return DocumentClassification(document_id="d", page_id="p", top_level_class=DocumentClass.CLAIM,
        document_family=DocumentClass.STANDARD_CLAIM, document_subtype=family, structured=structured,
        claim_related=True, standard_candidate=True, confidence=.99,
        supporting_evidence=("NOMINATION",), classifier_version="test")


def _cms_evidence():
    return StandardFormEvidence(candidate_family=DocumentClass.CMS1500, page_geometry_score=.9,
        region_layout_scores={"patient_insured": .9, "claim_information": .9,
                              "diagnosis": .9, "provider_billing": .9},
        service_grid_score=.9, high_value_anchor_score=.9, spatial_relationship_score=.9)


def _ub_evidence():
    return StandardFormEvidence(candidate_family=DocumentClass.UB04, page_geometry_score=.9,
        region_layout_scores={"institutional_grid": .9, "type_of_bill": .9,
                              "statement_covers": .9, "payer_provider": .9,
                              "revenue_service": .9, "diagnosis": .9},
        service_grid_score=.9, high_value_anchor_score=.9, spatial_relationship_score=.9,
        repeating_row_score=.9)


@pytest.mark.parametrize(("family", "evidence", "route"), [
    (DocumentClass.CMS1500, _cms_evidence(), ProcessingRoute.CMS_STANDARD_EXTRACTOR),
    (DocumentClass.UB04, _ub_evidence(), ProcessingRoute.UB_STANDARD_EXTRACTOR),
])
def test_fixed_extractor_requires_family_specific_verification(family, evidence, route):
    decision = DocumentRoutingDecisionService().decide_classification(_classification(family), evidence)
    assert decision.standard_verification.status == StandardFormStatus.VERIFIED
    assert decision.processing_route == route


@pytest.mark.parametrize("status", [StandardFormStatus.NOT_VERIFIED, StandardFormStatus.AMBIGUOUS])
def test_non_verified_contract_cannot_claim_fixed_extractor_eligibility(status):
    with pytest.raises(ValueError):
        StandardFormVerification(candidate_family=DocumentClass.CMS1500, status=status,
            verification_score=.5, eligible_for_fixed_extractor=True)


def test_missing_verification_fails_closed_and_preserves_structure():
    decision = DocumentRoutingDecisionService().decide_classification(_classification(DocumentClass.CMS1500))
    assert decision.standard_verification.status == StandardFormStatus.NOT_VERIFIED
    assert decision.processing_route == ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR


def test_visual_probability_alone_cannot_verify_standard_form():
    evidence = StandardFormEvidence(candidate_family=DocumentClass.UB04, visual_probability=1.0)
    decision = DocumentRoutingDecisionService().decide_classification(_classification(DocumentClass.UB04), evidence)
    assert decision.standard_verification.status == StandardFormStatus.NOT_VERIFIED
    assert decision.processing_route == ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR


def test_runtime_and_evaluation_use_identical_policy_results():
    service = DocumentRoutingDecisionService()
    classification = _classification(DocumentClass.UB04)
    runtime = service.decide_classification(classification, _ub_evidence(), evaluation_only=False)
    evaluation = service.decide_classification(classification, _ub_evidence(), evaluation_only=True)
    assert runtime.classification == evaluation.classification
    assert runtime.standard_verification == evaluation.standard_verification
    assert runtime.processing_route == evaluation.processing_route
