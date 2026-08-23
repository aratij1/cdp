from packages.document_taxonomy.corpus_v1 import (
    HierarchicalTruthLabel, IndependenceAttestation, PhiStatus, QualifiedRoutingCorpusManifest,
    RoutingTaxonomyPageRecord, SourceLineageRecord, StandardFormAuthority, UsageStatus,
)
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.processing_routes.contracts import ProcessingRoute
from evaluation.routing.freeze_qualified_corpus import freeze
from evaluation.routing.label_quality import agreement
from evaluation.routing.qualify_corpus import qualify


def _label(subtype=DocumentClass.CMS1500, route=ProcessingRoute.CMS_STANDARD_EXTRACTOR):
    return HierarchicalTruthLabel(top_level_class=DocumentClass.CLAIM,
        document_family=DocumentClass.STANDARD_CLAIM, subtype=subtype,
        expected_processing_route=route)


def _source(identifier="source-a"):
    return SourceLineageRecord(source_family_id=identifier, source_description="authorized test fixture",
        origin="internal fixture", acquisition_method="digital", renderer="fixture-renderer",
        template_lineage="cms-lineage-a", created_or_acquired_at="2026-08-23",
        relationship_to_other_sources="none", independence_rationale="independent fixture lineage",
        license_or_usage_status=UsageStatus.INTERNAL_APPROVED, phi_status=PhiStatus.PHI_FREE,
        source_independence_attestation=IndependenceAttestation.PASS)


def _page(identifier="page-a", digest="a" * 64, phash="0000000000000000"):
    label = _label()
    return RoutingTaxonomyPageRecord(document_id=f"doc-{identifier}", page_id=identifier,
        truth_top_level_class=label.top_level_class, truth_document_family=label.document_family,
        truth_subtype=label.subtype, expected_processing_route=label.expected_processing_route,
        source_family="source-a", source_instance="instance-a", renderer_family="renderer-a",
        template_lineage="cms-lineage-a", layout_family="cms-layout", acquisition_method="digital",
        digital_or_scan="DIGITAL", dpi_bucket="HIGH_DPI", quality_bucket="CLEAN",
        degradation_family="CLEAN", standard_form_authority=StandardFormAuthority.VERIFIED_STANDARD,
        reviewer_1_label=label, reviewer_2_label=label, adjudicated_label=label,
        file_sha256=digest, perceptual_hash=phash, layout_fingerprint="layout-fingerprint-a",
        base_asset_id="base-a", phi_status=PhiStatus.PHI_FREE,
        license_or_usage_status=UsageStatus.INTERNAL_APPROVED, image_readable=True,
        split_eligibility=True)


def test_source_independence_requires_attested_phi_and_usage_status():
    assert _source().qualified
    assert not _source().model_copy(update={"source_independence_attestation": "PARTIAL"}).qualified


def test_qualification_detects_exact_duplicates_and_blocks_freeze(tmp_path):
    manifest = QualifiedRoutingCorpusManifest(sources=(_source(),),
        pages=(_page("p1"), _page("p2")), minimum_pages=1,
        minimum_sources_per_priority_class=1, double_review_minimum_rate=.1)
    report = qualify(manifest)
    assert report["exact_duplicates"]
    assert not report["qualified"]
    try:
        freeze(manifest, tmp_path / "freeze.json")
    except ValueError as error:
        assert "CORPUS_QUALIFICATION_FAILED" in str(error)
    else:
        raise AssertionError("unqualified corpus freeze must fail")


def test_hierarchical_label_agreement_is_reported_per_level():
    result = agreement((_page(),))
    assert result["dimensions"]["top_level"]["raw_agreement"] == 1
    assert result["dimensions"]["processing_route"]["cohens_kappa"] == 1
