"""Provenance, form isolation, topology, row assembly and truth-leakage checks."""

import hashlib
import inspect
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from evaluation.cohort_topology import anchor_for
from evaluation.governed_30_candidate_coverage import ranks, unique_values
from workers.field_candidates.source_reviewed_anchor import (
    AUTHORITY,
    ReviewedSourceIdentity,
    SourceReviewedAnchor,
    anchored_tokens,
    discover_names,
)
from workers.page_detection.text_extraction import TextLine

SOURCE = b"synthetic reviewed source"
SHA = hashlib.sha256(SOURCE).hexdigest()
ANCHOR = SourceReviewedAnchor(
    SHA, "CMS1500", "patient_name", (0, 0, 200, 20), (0, 20, 200, 60), "form-topology-v1", AUTHORITY
)
IDENTITY = ReviewedSourceIdentity(SHA, "CMS1500", 0, AUTHORITY)


def token(text, x=10, y=25, right=100, bottom=45):
    return TextLine(text, x, y, right, bottom, 0.9)


def discover(tokens=None, **kwargs):
    defaults = {
        "image_bytes": SOURCE,
        "token_source_sha256": SHA,
        "identity": IDENTITY,
        "anchor": ANCHOR,
        "field_name": "patient_name",
        "rotation": 0,
    }
    defaults.update(kwargs)
    return discover_names(tokens or [token("JONES, ALICE")], **defaults)


@pytest.mark.parametrize("form", ["OTHER", "UNKNOWN", "UNSTRUCTURED", "UB", ""])
def test_wrong_or_unknown_form_abstains(form):
    assert discover(identity=replace(IDENTITY, form_type=form)) == []


@pytest.mark.parametrize("form", ["OTHER", "UNKNOWN", "UNSTRUCTURED"])
def test_matching_unknown_forms_still_abstain(form):
    assert (
        discover(identity=replace(IDENTITY, form_type=form), anchor=replace(ANCHOR, form_type=form))
        == []
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sha256": "0" * 64},
        {"field_name": "insured_name"},
        {"rotation": 180},
        {"anchor_version": "future"},
        {"review_provenance": "MODEL"},
        {"allowed_candidate_region": (200, 20, 0, 60)},
    ],
)
def test_anchor_guard_failures(changes):
    assert discover(anchor=replace(ANCHOR, **changes)) == []


def test_source_and_token_and_coordinate_frame_binding():
    assert discover(image_bytes=b"other source") == []
    assert discover(token_source_sha256="0" * 64) == []
    assert discover(rotation=180) == []
    assert discover(identity=replace(IDENTITY, provenance="ENGINEERING_REFERENCE")) == []


def test_spatial_assembly_preserves_middle_initial():
    result = discover(
        [token("JONES,", right=70), token("ALICE,", x=75, right=130), token("Q", x=140, right=150)]
    )
    assert result[0].value == "ALICE Q JONES"
    assert result[0].token_indices == (0, 1, 2)
    assert all(r.review_only for r in result)


def test_no_cross_column_or_next_row_copy():
    result = discover(
        [
            token("JONES, ALICE"),
            token("SMITH, BOB", x=220, right=350),
            token("BROWN, CAROL", y=70, bottom=90),
        ]
    )
    assert [r.value for r in result] == ["ALICE JONES", "JONES, ALICE"]


@pytest.mark.parametrize("raw", ["SAME", "SELF", "123 MAIN STREET", "4 INSURED NAME", "JONES 123"])
def test_semantics_labels_and_addresses_are_not_names(raw):
    assert discover([token(raw)]) == []


def test_no_ocr_character_repair():
    assert discover([token("J0NES, ALICE")]) == []
    assert discover([token("JONFS, ALICE")])[0].value == "ALICE JONFS"


def test_ub_period_separator_is_only_token_assembly():
    a = replace(ANCHOR, form_type="UB")
    i = replace(IDENTITY, form_type="UB")
    assert discover([token("Jones..Alice")], anchor=a, identity=i)[0].value == "Alice Jones"


def test_field_identity_cannot_be_swapped():
    assert discover(field_name="insured_name") == []


def test_registry_schema_rejects_truth_fields():
    for key in (
        "reference_value",
        "expected_ocr_string",
        "patient_name",
        "member_id",
        "dob",
        "diagnosis_value",
        "charge_value",
    ):
        with pytest.raises(TypeError):
            SourceReviewedAnchor(**{**asdict(ANCHOR), key: "forbidden"})
    assert "reference" not in inspect.signature(anchored_tokens).parameters
    assert "expected" not in inspect.signature(discover_names).parameters


def test_committed_registry_has_only_source_contract_fields():
    allowed = set(asdict(ANCHOR))
    registry = json.loads(
        Path(
            "docs/closure/largest_recoverable_cohort/source_reviewed_anchor_registry.json"
        ).read_text()
    )
    assert registry
    assert all(set(row) == allowed for row in registry)
    assert len({r["source_sha256"] for r in registry if r["form_type"] == "CMS1500"}) >= 2
    assert len({r["source_sha256"] for r in registry if r["form_type"] == "UB"}) >= 2


@pytest.mark.parametrize("scale", [0.5, 1, 2])
def test_topology_scales_without_reusing_source_hash(scale):
    page = {
        "form_type": "UB",
        "width": 1712 * scale,
        "height": 2214 * scale,
        "source_sha256": SHA,
        "rotation": 0,
    }
    anchor = anchor_for(page, "insured_name", [])
    assert anchor.allowed_candidate_region == (25 * scale, 1460 * scale, 525 * scale, 1555 * scale)


def test_cms_requires_observed_label_and_respects_address_boundary():
    page = {
        "form_type": "CMS1500",
        "width": 1712,
        "height": 2214,
        "source_sha256": SHA,
        "rotation": 0,
    }
    assert anchor_for(page, "patient_name", []) is None
    anchor = anchor_for(
        page,
        "patient_name",
        [
            token("2 PATIENT NAME", x=50, y=310, right=400, bottom=335),
            token("5. ADDRESS", x=50, y=375, right=400, bottom=390),
        ],
    )
    assert anchor.allowed_candidate_region == (40, 332, 605, 387)


def test_append_only_ranking_does_not_promote_old_alternatives():
    before = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "ALICE JONES"]
    after = unique_values("patient_name", before + ["ALICE JONES"])
    assert after == before
    assert not ranks("patient_name", "ALICE JONES", after)["5"]


def test_replay_report_has_fixed_denominators_and_no_critical_loss():
    score = json.loads(Path("docs/closure/largest_recoverable_cohort/scorecard.json").read_text())
    assert score["claims"] == 30
    assert score["metrics"]["all"]["before"]["R@5"]["numerator"] == 25
    assert score["metrics"]["critical"]["before"]["R@5"]["numerator"] == 22
    for family, denominator in (("all", 118), ("critical", 86)):
        for k in ("R@1", "R@3", "R@5"):
            assert score["metrics"][family]["after"][k]["denominator"] == denominator
            assert (
                score["metrics"][family]["after"][k]["numerator"]
                >= score["metrics"][family]["before"][k]["numerator"]
            )
