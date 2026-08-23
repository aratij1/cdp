import hashlib

import pytest

from packages.document_taxonomy import (
    BundleClass, CorpusRecord, DocumentClass, DocumentTaxonomyV1, HierarchicalRouteEvidence,
    PageClassification, ProcessingRoute, RoutingCorpusManifest, RoutingOutcome, assemble_observation,
    classify_bundle, summarize_outcomes, verify_standard_form,
)


def test_taxonomy_contains_canonical_hierarchy():
    assert DocumentTaxonomyV1.ancestors(DocumentClass.UB04) == (
        DocumentClass.STANDARD_CLAIM, DocumentClass.CLAIM, DocumentClass.DOCUMENT)
    assert set(DocumentTaxonomyV1.children_of(DocumentClass.DOCUMENT)) == {
        DocumentClass.CLAIM, DocumentClass.CLAIM_SUPPORT, DocumentClass.NON_CLAIM, DocumentClass.UNKNOWN}


def test_hierarchical_routing_abstains_at_missing_level():
    evidence = (HierarchicalRouteEvidence(evaluated_parent=DocumentClass.DOCUMENT,
        proposed_child=DocumentClass.CLAIM, confidence=.99, evidence_codes=("CLAIM_SEMANTICS",),
        source_component="deterministic-baseline"),)
    result = assemble_observation(evidence)
    assert result.abstained and result.terminal_label == DocumentClass.UNKNOWN
    assert result.evaluation_only


def test_form_nomination_cannot_authorize_without_all_traits():
    result = verify_standard_form(DocumentClass.UB04, {"form_locator_structure", "revenue_code_column"})
    assert not result.verified
    assert "institutional_service_grid" in result.missing_traits
    assert not hasattr(result, "authorized_route")


def test_processing_route_accuracy_is_separate_from_subtype_accuracy():
    outcome = RoutingOutcome(truth=DocumentClass.ITEMIZED_BILL, prediction=DocumentClass.MEDICAL_INVOICE,
                             authorized_route=ProcessingRoute.LAYOUT_STRUCTURED)
    metrics = summarize_outcomes((outcome,))
    assert metrics["exact_subtype_accuracy"] == 0
    assert metrics["processing_route_accuracy"] == 1
    assert outcome.risk_score == 5


def test_false_standard_authorization_is_highest_risk():
    outcome = RoutingOutcome(truth=DocumentClass.EOB, prediction=DocumentClass.UB04,
                             authorized_route=ProcessingRoute.UB_FIXED_TEMPLATE)
    assert outcome.false_standard_authorization and outcome.risk_score == 100


def test_safe_standard_fallback_is_efficiency_loss_not_safety_failure():
    outcome = RoutingOutcome(truth=DocumentClass.CMS1500, prediction=DocumentClass.CMS1500,
                             authorized_route=ProcessingRoute.LAYOUT_STRUCTURED,
                             verification_status="NOT_VERIFIED")
    metrics = summarize_outcomes((outcome,))
    assert outcome.safe_standard_fallback
    assert not outcome.false_standard_authorization
    assert metrics["safe_standard_fallback_rate"] == 1
    assert metrics["false_standard_authorization_rate"] == 0


def test_fixed_route_without_matching_verified_family_is_detected():
    outcome = RoutingOutcome(truth=DocumentClass.CMS1500, prediction=DocumentClass.CMS1500,
                             authorized_route=ProcessingRoute.CMS_STANDARD_EXTRACTOR,
                             verification_status="AMBIGUOUS")
    assert outcome.unverified_fixed_authorization


def test_bundle_keeps_page_and_document_classification_separate():
    pages = (PageClassification(page_number=1, taxonomy_class=DocumentClass.CMS1500),
             PageClassification(page_number=2, taxonomy_class=DocumentClass.LAB_REPORT))
    result = classify_bundle(pages)
    assert result.bundle_class == BundleClass.STANDARD_CLAIM_WITH_ATTACHMENTS
    assert result.pages[1].taxonomy_class == DocumentClass.LAB_REPORT
    assert not result.page_contradiction_overridden


def test_corpus_enforces_lineage_phi_and_source_split_leakage():
    digest = hashlib.sha256(b"one").hexdigest()
    record = CorpusRecord(document_id="d1", content_sha256=digest, label=DocumentClass.CMS1500,
        parent_path=(DocumentClass.DOCUMENT, DocumentClass.CLAIM, DocumentClass.STANDARD_CLAIM),
        source_id="s1", source_family="family-a", organization_id="org", acquisition_channel="scan",
        renderer_family="scanner-a", layout_family="cms-revision", template_family="cms-a",
        template_lineage="cms-a-lineage",
        document_origin_type="physical", degradation_family="fax", contains_phi=False)
    manifest = RoutingCorpusManifest(corpus_id="v1", records=(record,))
    assert "CMS1500" in manifest.representation_gaps()
    assert not manifest.quality_failures()
    with pytest.raises(ValueError):
        CorpusRecord(**{**record.model_dump(), "parent_path": (DocumentClass.DOCUMENT,)})
