import csv
import inspect
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from evaluation.phase8_8_generalization import (
    HOLDOUT_ID,
    SOURCE_IDS,
    replay_source,
    run_locked_holdout_once,
)
from packages.validation_rules.npi import is_valid_npi

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "evaluation_data/phase8_8_generalization"
RESULTS = ROOT / "evaluation_results/phase8_8"
V3 = ROOT / "evaluation_data/phase8_7_golden_pack/CDP_GOLDEN_ENGINEERING_PACK_V3"
pytestmark = pytest.mark.skipif(
    not (RESULTS / "decision.json").is_file() or not DATA.is_dir(),
    reason="governed Phase 8.8 generalization pack is not installed",
)


def _json(path: Path):
    return json.loads(path.read_text("utf-8"))


def test_dataset_firewall_has_fixed_roles_and_disjoint_lineage():
    registry = _json(RESULTS / "dataset_registry.json")

    assert registry["roles"] == ["DEV", "VALIDATION", "LOCKED_HOLDOUT", "ADVERSARIAL"]
    assert registry["source_disjoint"]
    assert registry["value_disjoint_from_v3"]
    assert not registry["random_split_used"]
    assert len({row["source_id"] for row in registry["datasets"]}) == 4
    assert len({row["renderer_lineage"] for row in registry["datasets"]}) == 4
    for source_id in SOURCE_IDS:
        assets = _json(DATA / source_id / "asset_registry.json")
        assert {row["dataset_role"] for row in assets} == {"DEV", "VALIDATION"}
        assert all(row["tuning_allowed"] == (row["dataset_role"] == "DEV") for row in assets)
        assert all(row["sha256"] and row["perceptual_hash"] for row in assets)
    holdout = _json(DATA / HOLDOUT_ID / "asset_registry.json")
    assert all(row["dataset_role"] == "LOCKED_HOLDOUT" for row in holdout)
    assert not any(row["tuning_allowed"] for row in holdout)


def test_phase8_8_values_are_disjoint_and_business_valid():
    with (V3 / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
        v3 = list(csv.DictReader(handle))
    old = defaultdict(set)
    for row in v3:
        old[row["field_name"]].add(row["expected_value"])

    for source_id in (*SOURCE_IDS, HOLDOUT_ID):
        with (DATA / source_id / "field_truth.csv").open(newline="", encoding="utf-8") as handle:
            fields = list(csv.DictReader(handle))
        for row in fields:
            if row["field_name"] != "relationship":
                assert row["expected_value"] not in old[row["field_name"]]
        npis = [row["expected_value"] for row in fields if row["field_name"] == "provider_npi"]
        assert npis and all(is_valid_npi(value) for value in npis)

        with (DATA / source_id / "ub04_service_line_truth.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            lines = list(csv.DictReader(handle))
        totals = defaultdict(lambda: Decimal(0))
        for row in lines:
            totals[row["document_id"]] += Decimal(row["charge"])
        truth_totals = {
            row["document_id"]: Decimal(row["expected_value"])
            for row in fields
            if row["field_name"] == "total_charge" and row["document_id"].split("-")[-2] == "UB"
        }
        assert totals == truth_totals


def test_source_disjoint_baseline_rejects_without_tuning_or_promotion():
    decision = _json(RESULTS / "decision.json")
    summary = _json(RESULTS / "generalization_summary.json")

    assert decision["decision"] == "REJECT"
    assert not decision["primary_generalization_gates_passed"]
    assert not decision["production_behavior_changed"]
    assert not decision["route_promoted"]
    assert decision["cloud_calls"] == 0
    assert summary["classification"] == "GENERALIZATION_FAILURE"
    assert summary["worst_source_claim_stp"] < 0.55
    assert summary["critical_false_accepts"] > 0


def test_loso_replay_is_ocr_free_and_source_aware():
    assert "OCRTextExtractor" not in inspect.getsource(replay_source)
    for suffix, source_id in zip("abc", SOURCE_IDS, strict=True):
        loso = _json(RESULTS / f"loso_{suffix}.json")
        assert loso["held_out_source"] == source_id
        assert len(loso["develop_sources"]) == 2
        assert not loso["random_split_used"]
        assert loso["candidate_rules_selected"] == []
        assert loso["held_out_metrics"]["documents"] == 14


def test_false_agreements_and_statistical_support_are_not_hidden():
    support = _json(RESULTS / "route_support.json")
    false_agreements = 0
    for source_id in SOURCE_IDS:
        metrics = _json(RESULTS / source_id.lower() / "local_evidence_metrics.json")
        false_agreements += sum(
            row["false_agreements"] for row in metrics["by_field"].values()
        )
    assert false_agreements > 0
    assert all(row["source_count"] == 3 for row in support["routes"])
    assert all(row["precision_wilson_95_lower"] < 0.999 for row in support["routes"])
    assert all(row["support"] == "INSUFFICIENT_SUPPORT" for row in support["routes"])


def test_adversarial_suite_fails_closed_and_holdout_remains_sealed():
    adversarial = _json(RESULTS / "adversarial_results.json")
    assert adversarial["all_cases_failed_closed"]
    assert all(row["failed_closed"] for row in adversarial["cases"])
    assert not (RESULTS / "locked_holdout_run.json").exists()
    with pytest.raises(RuntimeError, match="development gates failed"):
        run_locked_holdout_once(RESULTS)
    assert not (RESULTS / "locked_holdout_run.json").exists()
