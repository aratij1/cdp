import json

import pytest

from evaluation.untouched_holdout import (
    REQUIRED_CONDITIONS,
    HoldoutAsset,
    HoldoutAttestation,
    UntouchedHoldoutBuilder,
)


def _asset(number, family, conditions=None, source=None, digest=None):
    return HoldoutAsset(
        asset_id=f"asset-{number}", source_id=source or f"external-{number}",
        document_sha256=digest or f"{number:064x}", truth_sha256=f"{number + 100:064x}",
        perceptual_hash=f"{number:016x}", document_family=family,
        conditions=set(conditions or ()),
    )


def _attestation(**changes):
    values = dict(
        separate_source=True, never_threshold_tuned=True, never_prompt_tuned=True,
        never_used_for_ocr_selection=True, never_used_for_registration_adjustment=True,
        never_inspected_during_development=True, attested_by="data-governance",
        evidence_reference="approval-42",
    )
    values.update(changes)
    return HoldoutAttestation(**values)


def _assets():
    return [_asset(1, "CMS1500", REQUIRED_CONDITIONS), _asset(2, "UB04")]


def _builder(**changes):
    values = dict(development_hashes=set(), development_perceptual_hashes=set(),
                  development_source_ids=set(), minimum_documents=2)
    values.update(changes)
    return UntouchedHoldoutBuilder(**values)


def test_complete_external_dataset_freezes_and_verifies(tmp_path):
    path = tmp_path / "manifest.json"
    manifest = _builder().freeze(
        _assets(), _attestation(), dataset_version="v1", output=path
    )
    verified = UntouchedHoldoutBuilder.verify(path)
    assert manifest.manifest_sha256 == verified.manifest_sha256
    assert verified.status == "FROZEN"
    assert verified.composition["UB04"] == 1


def test_incomplete_attestation_and_composition_fail_closed(tmp_path):
    errors = _builder().audit(
        [_asset(1, "CMS1500")], _attestation(never_prompt_tuned=False)
    )
    assert "INCOMPLETE_UNTOUCHED_ATTESTATION" in errors
    assert "INSUFFICIENT_DOCUMENTS" in errors
    assert "MISSING_DOCUMENT_FAMILY" in errors
    assert "MISSING_COMPOSITION_CONDITION" in errors


@pytest.mark.parametrize(
    ("builder", "asset", "reason"),
    [
        (_builder(development_hashes={f"{9:064x}"}), _asset(9, "CMS1500"),
         "EXACT_DEVELOPMENT_OVERLAP"),
        (_builder(development_perceptual_hashes={f"{9:016x}"}), _asset(9, "CMS1500"),
         "PERCEPTUAL_DEVELOPMENT_OVERLAP"),
        (_builder(development_source_ids={"dev-source"}),
         _asset(9, "CMS1500", source="dev-source"), "DEVELOPMENT_SOURCE_REUSED"),
    ],
)
def test_development_overlap_is_rejected(builder, asset, reason):
    assert reason in builder.audit([asset, _asset(2, "UB04", REQUIRED_CONDITIONS)], _attestation())


def test_manifest_is_immutable_and_tamper_evident(tmp_path):
    path = tmp_path / "manifest.json"
    builder = _builder()
    builder.freeze(_assets(), _attestation(), dataset_version="v1", output=path)
    with pytest.raises(FileExistsError):
        builder.freeze(_assets(), _attestation(), dataset_version="v1", output=path)
    payload = json.loads(path.read_text("utf-8"))
    payload["dataset_version"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        UntouchedHoldoutBuilder.verify(path)
