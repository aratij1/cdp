"""Non-name localization, literal ID semantics and split-isolation checks."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from evaluation.non_name_inputs import reference_subset, refs
from evaluation.non_name_pilots import discover
from evaluation.non_name_strategy import MemberIdTopology, discover_member_ids
from workers.page_detection.text_extraction import TextLine


def token(text, x=610, y=120, right=760, bottom=140):
    return TextLine(text, x, y, right, bottom, 0.9)


def run(tokens=None, **kw):
    args = {
        "form_type": "CMS1500",
        "field_name": "member_id",
        "width": 1000,
        "height": 1000,
        "topology": MemberIdTopology(),
    }
    args.update(kw)
    return discover_member_ids(tokens or [token("AB00123-00")], **args)


@pytest.mark.parametrize("value", ["0012345", "AB00123-00", "A0B1C2", "R2257", "AB/0123"])
def test_preserve_source_characters_punctuation_and_leading_zero(value):
    assert run([token(value)])[0]["value"] == value


@pytest.mark.parametrize("form", ["UB", "OTHER", "UNKNOWN", "UNSTRUCTURED", ""])
def test_strict_form_gate(form):
    assert run(form_type=form) == []


def test_wrong_field_gate():
    assert run(field_name="patient_dob") == []


def test_own_region_only():
    assert run([token("ABC123", x=10, right=200)]) == []
    assert run([token("ABC123", y=350, bottom=380)]) == []


def test_cms_name_label_is_a_lower_boundary():
    label = token("4 INSURED NAME", x=600, y=130, right=850, bottom=145)
    assert run([label, token("1234567", y=138, bottom=148)]) == []


def test_contiguous_fragments_keep_observed_hyphen():
    result = run(
        [token("AB", right=630), token("-", x=631, right=638), token("001", x=639, right=669)]
    )
    assert result[0]["value"] == "AB-001"
    assert result[0]["token_indices"] == [0, 1, 2]


def test_spaced_fragments_are_not_joined_or_repaired():
    values = [r["value"] for r in run([token("AB01", right=650), token("234", x=720, right=760)])]
    assert "AB01234" not in values


def test_candidate_count_bound_and_review_only():
    result = run(
        [token("1234", right=650), token("5678", x=700, right=740), token("9012", x=820, right=860)]
    )
    assert len(result) == 2 and all(r["review_only"] for r in result)


@pytest.mark.parametrize("scale", [0.5, 1, 2])
def test_normalized_geometry_is_scale_invariant(scale):
    raw = token("AB001")
    t = replace(raw, x0=raw.x0 * scale, y0=raw.y0 * scale, x1=raw.x1 * scale, y1=raw.y1 * scale)
    assert run([t], width=int(1000 * scale), height=int(1000 * scale))[0]["value"] == "AB001"


def test_no_truth_fields_in_topology():
    for key in ["reference_value", "reference_length", "expected_characters", "source_sha256"]:
        with pytest.raises(TypeError):
            MemberIdTopology(**{**asdict(MemberIdTopology()), key: "forbidden"})


def test_dob_pilot_does_not_repair_letters():
    page = {"form_type": "UB", "width": 1000, "height": 1000}
    assert (
        discover("patient_dob", page, [token("1C041971", x=40, y=115, right=110, bottom=125)]) == []
    )
    assert (
        discover("patient_dob", page, [token("06241996", x=40, y=115, right=110, bottom=125)])[0][
            "value"
        ]
        == "1996-06-24"
    )


def test_charge_pilot_rejects_implied_decimals_and_wrong_form():
    t = token("12500", x=620, y=820, right=680, bottom=840)
    assert (
        discover("total_charge", {"form_type": "CMS1500", "width": 1000, "height": 1000}, [t]) == []
    )
    assert (
        discover(
            "total_charge",
            {"form_type": "UB", "width": 1000, "height": 1000},
            [replace(t, text="125.00")],
        )
        == []
    )


def test_package_claim_and_source_isolation():
    root = Path("docs/closure/non_name_cohort")
    dev = json.loads((root / "dev_manifest.json").read_text())
    val = json.loads((root / "validation_manifest.json").read_text())
    assert not set(dev["packages"]) & set(val["packages"])
    for collection, key in [
        ("claims", "claim_alias"),
        ("claims", "source_hash"),
        ("pages", "source_sha256"),
    ]:
        assert not {r[key] for r in dev[collection]} & {r[key] for r in val[collection]}
    assert len(dev["claims"]) + len(val["claims"]) == 30


def test_dev_materializer_never_decodes_validation_record(tmp_path):
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            [
                {"claim_alias": "DEV", "reference_value": "dev"},
                {"claim_alias": "VALIDATION", "reference_value": "forbidden"},
            ],
            indent=2,
        )
    )
    original = json.loads

    def guarded(value, *args, **kwargs):
        assert "forbidden" not in value and "VALIDATION" not in value
        return original(value, *args, **kwargs)

    with patch("evaluation.non_name_inputs.json.loads", side_effect=guarded):
        assert list(reference_subset(path, {"DEV"})) == [
            {"claim_alias": "DEV", "reference_value": "dev"}
        ]


def test_validation_references_blocked_before_freeze(tmp_path):
    with pytest.raises(ValueError, match="BEFORE_FREEZE"):
        refs(tmp_path, "validation")


def test_ambiguity_counts_distinct_alternatives_not_reference_mismatch():
    from evaluation.non_name_experiment import ambiguity

    rows = [{"field": "member_id", "before_values": [], "after_values": ["AB001"]}]
    assert ambiguity(rows)["new_non_equivalent_alternatives"] == 0
    rows[0]["after_values"].append("AB002")
    assert ambiguity(rows)["new_non_equivalent_alternatives"] == 1


@pytest.mark.skipif(
    not Path("evaluation_results/non_name_cohort/full_replay.local.json").exists(),
    reason="sealed local governed replay required",
)
def test_frozen_strategy_integrity():
    import hashlib
    import subprocess

    from evaluation.non_name_replay import frozen as historical_checkout_replay
    from evaluation.technical_closure import frozen as snapshot

    # The archived experiment is immutable after checkpoint commits. Validate
    # its actual frozen implementation bytes, not today's development HEAD.
    root = Path.cwd()
    manifest = json.loads(
        (root / "docs/closure/technical_closure/baseline64_manifest.json").read_text()
    )
    freeze = snapshot("docs/closure/non_name_cohort/non_name_strategy_freeze.json")
    assert freeze["selected_field"] == "member_id"
    expected = dict(freeze["implementation_hashes"])
    expected.update(
        {
            f"docs/closure/non_name_cohort/{split}_manifest.json": freeze[
                f"{split}_manifest_sha256"
            ]
            for split in ("dev", "validation")
        }
    )
    for name, sha in expected.items():
        entry = manifest["entries"][name]
        assert hashlib.sha256((root / entry["snapshot"]).read_bytes()).hexdigest() == sha
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if current != manifest["baseline_commit"]:
        with pytest.raises(ValueError, match="CHECKOUT_PROVENANCE_MISMATCH"):
            historical_checkout_replay()


@pytest.mark.skipif(
    not Path("evaluation_results/non_name_cohort/full_replay.local.json").exists(),
    reason="sealed local governed replay required",
)
def test_full_replay_preserves_names_and_fixed_denominators():
    before = json.loads(
        Path("evaluation_results/governed_30_cohort/replay_records.local.json").read_text()
    )
    after = json.loads(
        Path("evaluation_results/non_name_cohort/full_replay.local.json").read_text()
    )
    assert len(before) == len(after) == 118
    assert sum(r["critical"] for r in after) == 86
    mapping = {(r["claim_alias"], r["field"]): r for r in before}
    for row in after:
        old = mapping[row["claim_alias"], row["field"]]
        if row["field"] != "member_id":
            assert row["after_values"] == old["after_values"]
        assert all(not old["after"][k] or row["after"][k] for k in ("1", "3", "5"))


def test_strategy_freeze_has_no_reference_value_or_length_hint():
    freeze = json.loads(
        Path("docs/closure/non_name_cohort/non_name_strategy_freeze.json").read_text()
    )
    assert not set(freeze["topology"]) & {
        "reference_length",
        "reference_value",
        "expected_characters",
    }
    assert freeze["ranking"].startswith("APPEND_ONLY")
