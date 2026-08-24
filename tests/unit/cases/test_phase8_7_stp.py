import inspect
import json
import zipfile
from pathlib import Path

import pytest

from evaluation.phase8_7_stp import generate_valid_npi, replay_profiles
from packages.criticality import CriticalityLevel
from packages.domain.common import BoundingBox
from packages.evidence import StructuralLocalizationEvidence, StructuralLocalizationType
from packages.evidence_decision import DecisionContext, EvidenceDecisionService, FieldDisposition
from packages.ocr.contracts import OCRCandidate
from packages.validation_rules.npi import is_valid_npi

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "evaluation_results/phase8_7"
ACCEPTED = {FieldDisposition.AUTO_ACCEPTED, FieldDisposition.REFERENCE_CONFIRMED}
BOX = BoundingBox(x0=10, y0=10, x1=100, y1=30, image_width=200, image_height=200)
STRUCTURE = StructuralLocalizationEvidence(
    evidence_type=StructuralLocalizationType.ANCHOR_RELATIVE_LOCALIZATION_CONFIRMED,
    confidence=0.99,
    confirmed=True,
    reason_codes=("BOUNDED_ALIAS_MATCH", "OBSERVED_VALUE_TOKEN_GEOMETRY"),
    source="DYNAMIC_GEOMETRY:ANCHOR_RELATIVE",
)


def _candidate(value: str, engine: str) -> OCRCandidate:
    return OCRCandidate(
        value=value,
        raw_value=value,
        engine=engine,
        model_name=engine,
        model_version="phase8.7-test",
        preprocessing_variant="recorded-canonical-field-crop-v1",
        raw_confidence=0.99,
        calibrated_confidence=None,
        bounding_box=BOX,
        latency_ms=1,
        evidence_reference=f"phase8.7:{engine}:{value}",
    )


def _decision(field: str, family: str, values: tuple[str, str], valid: bool):
    return EvidenceDecisionService(route_mode="runtime").decide(
        DecisionContext(
            field_name=field,
            document_family=family,
            criticality=CriticalityLevel.C2,
            required=True,
            blocks_stp=True,
            candidates=[
                _candidate(values[0], "paddleocr"),
                _candidate(values[1], "rapidocr"),
            ],
            deterministic_evidence={"FORMAT_VALID"} if valid else set(),
            deterministic_evidence_version="phase8.7-test",
            hard_validation_passed=valid,
            structural_localization=STRUCTURE,
        )
    )


def test_valid_npi_generator_and_approved_cms_agreement_pass_safely():
    generated = [generate_valid_npi(f"fixture-{index}") for index in range(100)]
    assert len(set(generated)) == 100
    assert all(is_valid_npi(value) for value in generated)

    value = generated[0]
    decision = _decision("provider_npi", "CMS1500", (value, value), True)
    assert decision.disposition in ACCEPTED


def test_invalid_npi_and_tax_ocr_disagreement_fail_closed():
    invalid = "1234567890"
    assert not is_valid_npi(invalid)
    assert _decision("provider_npi", "CMS1500", (invalid, invalid), False).disposition not in ACCEPTED
    assert _decision(
        "federal_tax_no", "UB04", ("12-3456789", "98-7654321"), True
    ).disposition not in ACCEPTED


@pytest.mark.skipif(
    not (RESULTS / "golden_v3_validity.json").is_file(),
    reason="governed Phase 8.7 evidence pack is not installed",
)
def test_v3_validity_and_invalid_adversarial_partitions_are_complete():
    validity = json.loads((RESULTS / "golden_v3_validity.json").read_text("utf-8"))
    adversarial = json.loads(
        (RESULTS / "npi_invalid_adversarial.json").read_text("utf-8")
    )

    for field in ("provider_npi", "federal_tax_no", "patient_dob", "service_date"):
        assert validity["by_field"][field]["invalid"] == 0
    assert validity["by_field"]["UB04.claim_total_consistency"]["invalid"] == 0
    assert validity["required_provider_npis_all_valid"]
    assert adversarial["cases"] == 89
    assert adversarial["deterministic_failures"] == adversarial["cases"]
    assert adversarial["auto_accepts"] == 0
    assert adversarial["claim_stp_blocks"] == adversarial["cases"]
    assert all(not is_valid_npi(row["value"]) for row in adversarial["results"])


@pytest.mark.skipif(
    not (RESULTS / "CDP_GOLDEN_ENGINEERING_PACK_V3.zip").is_file(),
    reason="governed Phase 8.7 Golden V3 pack is not installed",
)
def test_v3_archive_proves_v1_v2_immutability_and_is_engineering_only():
    archive = RESULTS / "CDP_GOLDEN_ENGINEERING_PACK_V3.zip"
    with zipfile.ZipFile(archive) as bundle:
        provenance_name = next(
            name for name in bundle.namelist() if name.endswith("phase8_7_provenance.json")
        )
        manifest_name = next(name for name in bundle.namelist() if name.endswith("manifest.json"))
        provenance = json.loads(bundle.read(provenance_name))
        manifest = json.loads(bundle.read(manifest_name))

    assert provenance["v1_unchanged"] and provenance["v2_unchanged"]
    assert provenance["v1_tree_sha256_before"] == provenance["v1_tree_sha256_after"]
    assert provenance["v2_tree_sha256_before"] == provenance["v2_tree_sha256_after"]
    assert manifest["dataset_id"] == "CDP_GOLDEN_ENGINEERING_PACK_V3"
    assert not manifest["production_promotion_authority"]


@pytest.mark.skipif(
    not (RESULTS / "decision.json").is_file(),
    reason="governed Phase 8.7 evidence pack is not installed",
)
def test_policy_replay_is_ocr_free_and_stops_at_first_safe_frontier():
    assert "OCRTextExtractor" not in inspect.getsource(replay_profiles)
    baseline = json.loads((RESULTS / "v3_baseline.json").read_text("utf-8"))
    candidate = json.loads((RESULTS / "v3_name_evidence.json").read_text("utf-8"))
    decision = json.loads((RESULTS / "decision.json").read_text("utf-8"))

    assert candidate["claim_stp"] > baseline["claim_stp"]
    assert candidate["claim_stp"] >= 0.50
    assert candidate["accepted_precision"] >= 0.999
    assert candidate["critical_false_accepts"] == 0
    assert candidate["cloud_calls"] == 0
    assert decision["stop_condition_reached"]
    assert not decision["second_frontier_attempted"]
    assert not decision["production_route_promoted_from_v3"]
