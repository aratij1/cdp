"""Synthetic completeness and no-promotion tests for runtime field policies."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from packages.evidence import EvidencePolicy
from packages.evidence_decision import DecisionContext, FieldDisposition
from packages.field_policy import DEFAULT_FIELD_POLICY_PATH, FieldPolicyRegistry
from packages.runtime_policy_coverage import policy_coverage, supported_runtime_fields
from packages.runtime_profile import DecisionServiceFactory
from packages.runtime_profile.contracts import CANONICAL_RUNTIME_PROFILE_PATH
from tests.unit.cases.test_evidence_decision_service import candidate


def payload():
    return yaml.safe_load(DEFAULT_FIELD_POLICY_PATH.read_text(encoding="utf-8"))


def test_all_actual_runtime_emitters_have_explicit_contracts():
    bundle = DecisionServiceFactory.from_profile()
    report = policy_coverage(bundle.field_policy, bundle.evidence_decision.evidence_policy)
    assert report["status"] == "READY" and report["uncovered"] == 0
    assert report["supported_field_family_pairs"] >= 178
    assert not report["automation_approval_implied"]


@pytest.mark.parametrize("missing", ["policy", "criticality", "required", "validation_rule",
                                     "validation_version", "evidence_requirements", "disposition_mode"])
def test_missing_component_prevents_readiness(missing):
    data = payload()
    if missing == "policy": data["forms"]["UNSTRUCTURED"].pop("provider_npi")
    else: data["forms"]["UNSTRUCTURED"]["provider_npi"].pop(missing)
    report = policy_coverage(FieldPolicyRegistry(data), EvidencePolicy.load())
    assert report["status"] == "CONFIGURATION_INCOMPLETE"
    row = next(r for r in report["fields"] if r["family"] == "UNSTRUCTURED" and r["field"] == "provider_npi")
    assert row["failures"]


def test_new_emitter_field_without_policy_is_not_hidden_by_default():
    inventory = supported_runtime_fields()
    inventory["UNSTRUCTURED"].add("newly_emitted_field")
    assert policy_coverage(FieldPolicyRegistry.load(), EvidencePolicy.load(), inventory)["status"] == "CONFIGURATION_INCOMPLETE"


def test_matching_file_hash_does_not_bypass_coverage(tmp_path):
    data = payload()
    data["forms"]["UNSTRUCTURED"].pop("provider_npi")
    policy = tmp_path / "policy.yaml"
    policy.write_text(yaml.safe_dump(data), encoding="utf-8")
    profile = yaml.safe_load(CANONICAL_RUNTIME_PROFILE_PATH.read_text())
    profile.update(field_policy_path=str(policy), field_policy_sha256=hashlib.sha256(
        policy.read_bytes().replace(b"\r\n", b"\n")).hexdigest())
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="CONFIGURATION_INCOMPLETE"):
        DecisionServiceFactory.from_profile(path)


def test_http_readiness_returns_503_on_incomplete_policy(monkeypatch):
    from apps.ingestion_api import main

    monkeypatch.setitem(main._state, "session_factory", object())
    monkeypatch.setitem(main._state, "object_store", object())
    def incomplete(*args, **kwargs):
        raise ValueError("CONFIGURATION_INCOMPLETE")
    monkeypatch.setattr(DecisionServiceFactory, "from_profile", incomplete)
    with pytest.raises(HTTPException) as error: main.ready()
    assert error.value.status_code == 503 and error.value.detail == "CONFIGURATION_INCOMPLETE"


def test_high_confidence_cannot_promote_review_only_field():
    bundle = DecisionServiceFactory.from_profile()
    policy = bundle.field_policy.for_field("UNSTRUCTURED", "provider_npi")
    result = bundle.evidence_decision.decide(DecisionContext(
        field_name="provider_npi", document_family="UNSTRUCTURED", criticality=policy.criticality,
        candidates=[candidate("paddleocr", "1234567893", 1), candidate("rapidocr", "1234567893", 1)],
        hard_validation_passed=True, deterministic_evidence={"CHECKSUM_VALID"},
    ))
    assert result.disposition is FieldDisposition.HUMAN_REVIEW_REQUIRED
    assert "GOVERNED_REVIEW_REQUIRED" in result.reason_codes
    assert "FIELD_POLICY_NOT_CONFIGURED" not in result.reason_codes


def test_existing_automatic_contracts_are_unchanged():
    old = yaml.safe_load(Path("config/field_acceptance_policies.yaml").read_text())
    new = payload()
    for family, fields in old["forms"].items():
        for name, specification in fields.items():
            current = copy.deepcopy(new["forms"][family][name])
            for metadata in ("validation_rule", "validation_version", "disposition_mode", "evidence_requirements"):
                current.pop(metadata)
            assert current == specification
    old_profile = yaml.safe_load(Path("config/runtime_profiles/canonical_runtime_v1.yaml").read_text())
    current_profile = yaml.safe_load(CANONICAL_RUNTIME_PROFILE_PATH.read_text())
    for field in ("evidence_policy", "route_registry", "criticality_config", "claim_policy", "reference_config", "calibration_registry"):
        assert current_profile[field+"_sha256"] == old_profile[field+"_sha256"]
