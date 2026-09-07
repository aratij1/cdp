"""Prospective isolation guards and normalized-geometry contract checks."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from evaluation.name_topology_development import derive
from evaluation.name_topology_provenance import validated_baseline_sha
from evaluation.name_topology_rule import NameFieldTopology, Registration, discover
from workers.page_detection.text_extraction import TextLine

RULE = NameFieldTopology("CMS1500", "patient_name", (0.02, 0.1, 0.36, 0.22))


def source(scale=1, dx=0, dy=0):
    return [
        TextLine(text, (l - dx) * scale, (t - dy) * scale, (r - dx) * scale, (b - dy) * scale, 0.9)
        for text, l, t, r, b in [
            ("2 PATIENT NAME", 30, 120, 300, 140),
            ("JONES, ALICE", 40, 150, 230, 170),
            ("5. ADDRESS", 30, 185, 300, 200),
        ]
    ]


def run(tokens=None, **kw):
    args = {
        "form_type": "CMS1500",
        "field_name": "patient_name",
        "width": 1000,
        "height": 1000,
        "topology": RULE,
    }
    args.update(kw)
    return discover(source() if tokens is None else tokens, **args)


@pytest.mark.parametrize("scale", [0.5, 1, 2, 4])
def test_resolution_invariance(scale):
    result, _ = run(source(scale), width=int(1000 * scale), height=int(1000 * scale))
    assert result[0]["value"] == "ALICE JONES"


@pytest.mark.parametrize("dx,dy", [(10, 10), (-10, -10), (15, -5)])
def test_bounded_registered_translation(dx, dy):
    result, _ = run(source(dx=dx, dy=dy), registration=Registration(dx / 1000, dy / 1000))
    assert result[0]["value"] == "ALICE JONES"


def test_small_deskew_preserves_cell_and_large_transform_abstains():
    assert run(registration=Registration(skew=0.01))[0]
    assert run(registration=Registration(skew=0.1)) == ([], [])


@pytest.mark.parametrize("form", ["UB", "OTHER", "UNKNOWN", "UNSTRUCTURED", ""])
def test_strict_form_identity(form):
    assert run(form_type=form) == ([], [])


def test_field_identity_and_invalid_geometry():
    assert run(field_name="insured_name") == ([], [])
    assert run(topology=replace(RULE, normalized_region=(0.4, 0.1, 0.2, 0.3))) == ([], [])


@pytest.mark.parametrize("placeholder", ["SAME", "SAME AS ABOVE", "SELF"])
def test_placeholder_is_observation_not_name(placeholder):
    tokens = source()
    tokens[1] = replace(tokens[1], text=placeholder)
    values, observations = run(tokens)
    assert values == []
    assert observations[0]["resolution"] == "NO_GOVERNED_FIELD_INHERITANCE_AUTHORITY"


def test_topology_schema_contains_no_image_or_truth_fields():
    keys = set(asdict(RULE))
    assert not keys & {
        "image_hash",
        "source_sha256",
        "reference_value",
        "patient_name",
        "insured_name",
    }
    with pytest.raises(TypeError):
        NameFieldTopology(**{**asdict(RULE), "reference_value": "forbidden"})


def test_large_token_gap_is_not_assembled():
    tokens = [
        TextLine("2 PATIENT NAME", 30, 120, 300, 140, 0.9),
        TextLine("JONES", 30, 150, 70, 170, 0.9),
        TextLine("ALICE", 300, 150, 345, 170, 0.9),
    ]
    assert run(tokens)[0] == []


def test_adjacent_column_does_not_supply_name():
    tokens = source()
    tokens[1] = replace(tokens[1], x0=600, x1=800)
    assert run(tokens)[0] == []


def test_package_claim_and_source_isolation():
    root = Path("docs/closure/name_topology_generalization")
    dev = json.loads((root / "name_topology_dev.json").read_text())
    val = json.loads((root / "name_topology_validation.json").read_text())
    assert not set(dev["package_hashes"]) & set(val["package_hashes"])
    for key, collection in (("claim_alias", "claims"), ("source_sha256", "pages")):
        assert not {r[key] for r in dev[collection]} & {r[key] for r in val[collection]}
    assert len(dev["claims"]) + len(val["claims"]) == 30


def test_development_cannot_read_any_reference_or_validation_tokens():
    original = Path.read_text
    accesses = []

    def guarded(path, *args, **kwargs):
        name = path.as_posix()
        assert not any(
            x in name
            for x in (
                "reference.local",
                "replay_records",
                "root_collapse_records",
                "/records.local",
            )
        )
        if "tokens/" in name:
            assert "CLM_A_" in name or "CLM_D_" in name
        accesses.append(name)
        return original(path, *args, **kwargs)

    with patch.object(Path, "read_text", guarded):
        rules = derive(Path.cwd())
    assert rules and accesses
    assert all(rule.form_type == "CMS1500" for rule in rules)


def test_checkout_mismatch_fails_closed():
    with (
        patch("evaluation.name_topology_provenance.subprocess.check_output", return_value="0" * 40),
        pytest.raises(ValueError, match="PROVENANCE"),
    ):
        validated_baseline_sha(Path.cwd())


def test_ambiguity_does_not_use_reference_equality():
    from evaluation.name_topology_validation import ambiguity

    row = {
        "before_values": ["JONES, ALICE"],
        "after_values": ["JONES, ALICE", "ALICE JONES", "ALICE SMITH"],
    }
    report = ambiguity([row])
    assert report["after"]["token_equivalent_duplicates"] == 1
    assert report["after"]["non_equivalent_alternatives"] == 1
    assert report["new_non_equivalent_ambiguity_blockers"] == 1


def test_freeze_rejects_implementation_mutation():
    from evaluation.name_topology_validation import verify_freeze

    with (
        # Checkout provenance has a separate negative test above. Isolate the
        # implementation-mutation guard from the current development HEAD.
        patch("evaluation.name_topology_validation.validated_baseline_sha", return_value="b" * 40),
        patch("evaluation.name_topology_validation.sha", return_value="changed"),
        pytest.raises(
            ValueError, match="SOURCE_IDENTITY_CATALOG_CHANGED|FROZEN_IMPLEMENTATION_CHANGED"
        ),
    ):
        verify_freeze(Path.cwd())
