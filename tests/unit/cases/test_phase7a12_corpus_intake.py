from datetime import UTC, datetime

from PIL import Image

from evaluation.corpus_intake.contracts import (
    BlindReviewRecord,
    ConfidenceBucket,
    CorpusAssetIntakeRecord,
    CorpusIntakeBatch,
    QualificationStatus,
    ReviewStatus,
    SourceLineageAttestation,
    StandardFamily,
    StandardStatus,
)
from evaluation.corpus_intake.integrity import inspect_asset
from evaluation.corpus_intake.qualification import (
    assess_source_attestations,
    audit_leakage,
    record_residual_leakage,
    source_hash_manifest,
)
from evaluation.corpus_intake.review import create_blind_assignments, resolve_reviews
from evaluation.corpus_intake.workflow import PHASE7A12_OUTPUT_FILES, run_phase7a12
from packages.document_taxonomy.corpus_v1 import (
    IndependenceAttestation,
    PhiStatus,
    UsageStatus,
)
from packages.document_taxonomy.taxonomy import DocumentClass
from packages.processing_routes.contracts import ProcessingRoute
from packages.storage.hashing import perceptual_hash, sha256_file

NOW = datetime(2026, 8, 23, tzinfo=UTC)


def _asset(path, **updates):
    with Image.open(path) as image:
        phash = perceptual_hash(image)
    values = {
        "asset_id": "asset-a", "document_id": "document-a", "page_id": "page-a",
        "asset_uri": path.name, "asset_sha256": sha256_file(str(path)), "perceptual_hash": phash,
        "mime_type": "image/png", "page_count": 1, "source_family_id": "source-a",
        "source_instance_id": "instance-a", "template_lineage_id": "template-a",
        "renderer_lineage_id": "renderer-a", "layout_family": "cms-layout",
        "acquisition_method": "controlled-acquisition", "degradation_family": "clean",
        "phi_status": PhiStatus.PHI_FREE, "usage_status": UsageStatus.INTERNAL_APPROVED,
        "license_or_authorization_reference": "approval-ticket-a",
        "truth_top_level_class": DocumentClass.CLAIM,
        "truth_document_family": DocumentClass.STANDARD_CLAIM,
        "truth_subtype": DocumentClass.CMS1500,
        "expected_processing_route": ProcessingRoute.CMS_STANDARD_EXTRACTOR,
        "review_status": ReviewStatus.PENDING, "split_eligibility": True,
        "qualification_status": QualificationStatus.PENDING_ATTESTATION,
    }
    values.update(updates)
    return CorpusAssetIntakeRecord(**values)


def _review(asset_id="asset-a", reviewer_id="reviewer-a", **updates):
    values = {
        "reviewer_id": reviewer_id, "review_session_id": f"session-{reviewer_id}",
        "asset_id": asset_id, "top_level_label": DocumentClass.CLAIM,
        "document_family": DocumentClass.STANDARD_CLAIM,
        "standard_status": StandardStatus.STANDARD, "standard_family": StandardFamily.CMS1500,
        "subtype": DocumentClass.CMS1500,
        "expected_processing_route": ProcessingRoute.CMS_STANDARD_EXTRACTOR,
        "ambiguity": False, "ambiguity_reason": "NONE", "confidence_bucket": ConfidenceBucket.HIGH,
        "created_at": NOW, "blind_to_other_reviews": True,
    }
    values.update(updates)
    return BlindReviewRecord(**values)


def _attestation(asset):
    return SourceLineageAttestation(
        source_family_id=asset.source_family_id, source_description="authorized fixture source",
        origin_type="internal-test", acquisition_method=asset.acquisition_method,
        template_lineage_id=asset.template_lineage_id,
        renderer_lineage_id=asset.renderer_lineage_id, relationship_to_other_sources=(),
        independence_rationale="separate controlled fixture origin",
        usage_status=UsageStatus.INTERNAL_APPROVED, phi_status=PhiStatus.PHI_FREE,
        reviewer_id="governance-reviewer", review_timestamp=NOW,
        source_hash_manifest=source_hash_manifest([asset]),
        independence_status=IndependenceAttestation.PASS,
        authorization_reference="approval-ticket-a",
    )


def test_empty_intake_stops_needs_more_data_and_writes_all_required_outputs(tmp_path):
    output = tmp_path / "results"
    result = run_phase7a12(CorpusIntakeBatch(), root=tmp_path.parent,
                           output_dir=output,
                           baseline_path=tmp_path / "not-needed-for-empty.json")
    assert result["decision"]["DECISION"] == "NEEDS_MORE_DATA"
    assert result["decision"]["LOSO STATUS"] == "BLOCKED"
    assert {path.name for path in output.iterdir()} == set(PHASE7A12_OUTPUT_FILES)
    assert result["artifacts"]["corpus_freeze.json"]["freeze_status"] == "NOT_CREATED"


def test_integrity_uses_controlled_relative_path_and_recomputes_hashes(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (64, 64), "white").save(path)
    asset = _asset(path)
    assert inspect_asset(asset, tmp_path)["integrity_passed"]
    escaped = asset.model_copy(update={"asset_uri": "../page.png"})
    evidence = inspect_asset(escaped, tmp_path)
    assert not evidence["integrity_passed"]
    assert "ASSET_URI_ESCAPES_CONTROLLED_ROOT" in evidence["reason_codes"]


def test_source_pass_requires_exact_hash_manifest_and_governed_statuses(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (64, 64), "white").save(path)
    asset = _asset(path)
    assert assess_source_attestations((asset,), (_attestation(asset),))["source-a"]["status"] == "PASS"
    wrong = _attestation(asset).model_copy(update={"source_hash_manifest": "0" * 64})
    result = assess_source_attestations((asset,), (wrong,))["source-a"]
    assert result["status"] == "FAIL"
    assert "SOURCE_HASH_MANIFEST_MISMATCH" in result["reason_codes"]


def test_blind_assignment_never_exposes_labels_and_review_disagreement_requires_adjudication(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (64, 64), "white").save(path)
    asset = _asset(path, asset_id="requires-double-confuser",
                   truth_document_family=DocumentClass.NON_STANDARD_CLAIM,
                   truth_subtype=DocumentClass.CUSTOM_PROFESSIONAL,
                   expected_processing_route=ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR)
    assignments = create_blind_assignments((asset,), ("reviewer-a", "reviewer-b"))
    assert len(assignments) == 2
    assert all(item["labels_visible"] is False for item in assignments)
    first = _review(asset_id=asset.asset_id)
    second = _review(asset_id=asset.asset_id, reviewer_id="reviewer-b",
                     top_level_label=DocumentClass.CLAIM_SUPPORT,
                     document_family=DocumentClass.CLAIM_SUPPORT,
                     standard_status=StandardStatus.NOT_APPLICABLE,
                     standard_family=StandardFamily.NONE,
                     subtype=DocumentClass.EOB,
                     expected_processing_route=ProcessingRoute.LAYOUT_STRUCTURED_EXTRACTOR)
    resolutions, report = resolve_reviews((asset,), (first, second), ())
    assert resolutions[asset.asset_id]["review_status"] == "PENDING_ADJUDICATION"
    assert not resolutions[asset.asset_id]["resolved"]
    assert report["unresolved_critical_disagreements"] == 1


def test_duplicate_or_related_cross_source_assets_are_blocked(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (64, 64), "white").save(path)
    first = _asset(path)
    second = _asset(path, asset_id="asset-b", document_id="document-b", page_id="page-b",
                    source_family_id="source-b", source_instance_id="instance-b")
    report = audit_leakage((first, second))
    assert report["exact_duplicate_leakage_count"] == 1
    assert set(report["blocked_asset_ids"]) == {"asset-a", "asset-b"}
    record_residual_leakage(report, {
        "asset-a": {"qualification_status": "EXCLUDED"},
        "asset-b": {"qualification_status": "EXCLUDED"},
    })
    assert report["residual_exact_duplicate_leakage_count"] == 0


def test_truth_must_use_the_exact_leaf_path(tmp_path):
    path = tmp_path / "page.png"
    Image.new("RGB", (64, 64), "white").save(path)
    try:
        _asset(path, truth_top_level_class=DocumentClass.DOCUMENT)
    except ValueError as error:
        assert "top-level" in str(error)
    else:
        raise AssertionError("an ancestor is not a valid top-level truth label")
