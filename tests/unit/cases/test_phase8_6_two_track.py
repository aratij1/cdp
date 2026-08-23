import inspect
import json
import zipfile
from pathlib import Path

import yaml
from PIL import Image

from evaluation.phase8_6_two_track import render_tax_field, targeted_replay

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "evaluation_results/phase8_6"


def test_ub_v2_renders_a_truth_measurable_tax_field_in_the_explicit_region():
    image = Image.new("RGB", (1400, 1800), "white")

    rendered, bbox = render_tax_field(image, "UB007", "clean")

    assert rendered == "980000007"
    assert bbox == [900, 415, 1017, 432]
    assert image.crop((890, 370, 1329, 460)).getextrema() == ((0, 255),) * 3
    assert image.crop((0, 0, 800, 300)).getextrema() == ((255, 255),) * 3


def test_corrected_archive_has_50_ub_tax_truth_rows_and_preserves_100_documents():
    archive = RESULTS / "CDP_GOLDEN_ENGINEERING_PACK_V2.zip"
    with zipfile.ZipFile(archive) as bundle:
        manifest_name = next(name for name in bundle.namelist() if name.endswith("manifest.json"))
        truth_name = next(name for name in bundle.namelist() if name.endswith("field_truth.csv"))
        manifest = json.loads(bundle.read(manifest_name))
        truth = bundle.read(truth_name).decode("utf-8").splitlines()

    assert manifest["dataset_id"] == "CDP_GOLDEN_ENGINEERING_PACK_V2"
    assert len(manifest["documents"]) == 100
    assert len(truth) == 1001
    assert sum(",federal_tax_no," in line for line in truth) == 50


def test_only_zero_false_agreement_routes_are_production_approved():
    cms = json.loads((RESULTS / "cms_local_evidence_metrics.json").read_text("utf-8"))
    ub = json.loads((RESULTS / "ub_federal_tax_metrics.json").read_text("utf-8"))
    config = yaml.safe_load((ROOT / "config/ocr_field_routes.yaml").read_text("utf-8"))

    for field_name in ("provider_npi", "total_charge"):
        assert cms["by_field"][field_name]["promotion_gate_passed"]
        assert cms["by_field"][field_name]["false_agreements"] == 0
        assert config["ocr_routes"][field_name]["status"] == "PRODUCTION_APPROVED"
    assert ub["promotion_gate_passed"]
    assert ub["false_agreements"] == 0
    assert config["ocr_routes"]["federal_tax_no"]["status"] == "PRODUCTION_APPROVED"


def test_targeted_replay_is_ocr_free_and_preserves_the_safety_gate():
    assert "OCRTextExtractor" not in inspect.getsource(targeted_replay)
    decision = json.loads((RESULTS / "decision.json").read_text("utf-8"))

    assert decision["ocr_invocations_during_policy_replay"] == 0
    assert decision["safety_gate_passed"]
    assert decision["profile_c"]["false_accepts"] == 0
    assert decision["profile_c"]["critical_false_accepts"] == 0
