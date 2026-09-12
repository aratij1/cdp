from pathlib import Path

from packages.release_freeze import sha256_file, verify_release_manifest


def test_frozen_baseline_manifest_and_configuration_are_valid():
    release = Path("config/releases/extraction-v2.yaml")
    before = sha256_file(release)
    verify_release_manifest(
        release, configuration_root=Path("config/releases/extraction-v2.snapshot")
    )
    after = sha256_file(release)
    assert before == after


def test_frozen_snapshot_rejects_modified_configuration(tmp_path):
    import json

    import pytest

    release = tmp_path / "manifest.yaml"
    config = tmp_path / "config.yaml"
    config.write_text("version: approved\n")
    release.write_text(json.dumps({"status": "FROZEN", "configuration_hashes": {
        "config.yaml": sha256_file(config)}}))
    verify_release_manifest(release, configuration_root=tmp_path)
    config.write_text("version: changed\n")
    with pytest.raises(ValueError, match="changed without a new release"):
        verify_release_manifest(release, configuration_root=tmp_path)
