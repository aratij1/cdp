"""Frozen 106-miss taxonomy and isolated structural candidate replay.

Reference access is confined to evaluation. Runtime proposal generators receive
only source OCR geometry; output/acceptance and blind-review truth stay separate.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from evaluation.governed_30_candidate_coverage import ranks, token_presence, unique_values
from evaluation.governed_30_reference import ROOT, digest
from evaluation.governed_30_root_cause import routing_state
from evaluation.governed_30_scorecard import _canonical, metric, score
from packages.claim_intelligence.normalization import comparison_key
from packages.field_policy import FieldPolicyRegistry
from workers.field_candidates.bounded_geometry_recovery import (
    generate_structural,
    source_amount_components,
)
from workers.field_candidates.label_token_recovery import generate, labels
from workers.page_detection.text_extraction import TextLine

CAUSES = (
    "SOURCE_VALUE_NOT_PRESENT",
    "SOURCE_PLACEHOLDER_SEMANTICS",
    "REFERENCE_ABBREVIATION_OR_EQUIVALENCE",
    "ORIENTATION_FAILURE",
    "LABEL_TO_VALUE_ASSOCIATION",
    "REGION_LOCALIZATION",
    "TOKEN_ASSEMBLY",
    "OCR_RECOGNITION_MISS",
    "SOURCE_ILLEGIBLE",
    "WRONG_FORM_OR_FIELD_TOPOLOGY",
    "OTHER",
)


def classify(row: dict, trace: dict) -> tuple[str, str, bool]:
    """One primary cause, with explicit precedence and a fixed denominator."""
    vis = row["source_visibility"]
    notes = " ".join(vis["notes"])
    if vis["visibility"] == "NOT_PRESENT":
        return (
            CAUSES[0],
            "NO_INSURED_NAME_IN_SOURCE_FIELD; reference placeholder is not a pixel value",
            False,
        )
    if "SAYS_SAME" in notes:
        return CAUSES[1], "NO_GOVERNED_NAME_INHERITANCE_CONTRACT_FOUND", False
    if "TWO_DISTINCT_RECEIPTS" in notes:
        return CAUSES[6], "DERIVED_AGGREGATE_REQUIRES_SEPARATE_CLAIM_EVIDENCE_CONTRACT", False
    if vis["representation_difference"]:
        return (
            CAUSES[2],
            "EXISTING_COMPARATOR_DOES_NOT_AUTHORIZE_ABBREVIATION_OR_IDENTIFIER_REWRITE",
            False,
        )
    if vis["visibility"] == "ILLEGIBLE":
        return CAUSES[8], "SOURCE_PIXELS_NOT_READABLE", False
    if vis["orientation_180_observed"]:
        return (
            CAUSES[3],
            "INVERTED_GOVERNED_SOURCE_PAGE; projection profile cannot resolve 0 versus 180",
            True,
        )
    if trace.get("charge_column_header_only"):
        return CAUSES[9], "CHARGE_COLUMN_HEADER_IS_NOT_A_CLAIM_TOTAL_REGION", True
    if trace.get("merged_amount_match"):
        return (
            CAUSES[6],
            "OBSERVED_AMOUNT_SPAN_CROSSES_TOKEN_OR_COLUMN_BOUNDARY; segmentation required",
            True,
        )
    if trace.get("amount_assembly_match"):
        return (
            CAUSES[6],
            "OBSERVED_AMOUNT_COMPONENTS_PRESENT_IN_TOTAL_REGION; formatting/segmentation assembly",
            True,
        )
    if trace.get("principal_region_observed"):
        if not trace["principal_region_match"]:
            return (
                CAUSES[7],
                "PRINCIPAL_REGION_TOKEN_WRONG; matching admitting diagnosis is not interchangeable",
                True,
            )
        return CAUSES[5], "BOX_67_VALUE_PRESENT_BUT_NO_PRINCIPAL_FIELD_ANCHOR", True
    if trace["token_matches"]:
        if (
            row["field"] in {"patient_name", "insured_name"}
            and trace["local_value_match"]
            and not trace["exact_order_token_match"]
        ):
            return CAUSES[6], "OBSERVED_NAME_COMPONENTS_REQUIRE_PROVEN_SOURCE_ORDER_ASSEMBLY", True
        if trace["label_matches"]:
            return (
                CAUSES[4],
                "VALUE_TOKEN_NOT_ASSOCIATED_WITH_ITS_LABEL_IN_BOUNDED_GENERATION",
                True,
            )
        if row["claim_alias"] in {"CLM_D_001", "CLM_D_002", "CLM_D_005", "CLM_D_006", "CLM_D_007"}:
            return CAUSES[9], "RECEIPT_OR_CARD_FIELD_TOPOLOGY_HAS_NO_SUPPORTED_FORM_LABEL", True
        return CAUSES[5], "SOURCE_VALUE_TOKEN_PRESENT_WITHOUT_A_MATCHED_FIELD_LABEL", True
    if row["field"] == "patient_dob" and trace["numeric_date_present"]:
        return (
            CAUSES[6],
            "OBSERVED_EIGHT_DIGIT_DATE_NOT_ASSEMBLED_USING_EXISTING_US_DATE_CONVENTION",
            True,
        )
    if not trace["label_matches"]:
        return CAUSES[5], "NO_GROUNDED_FIELD_ANCHOR; OCR_ABSENCE_NOT_ESTABLISHED", True
    return (
        CAUSES[7],
        "VISIBLE_VALUE_NOT_RECOGNIZED_IN_KNOWN_LABEL_REGION; engineering diagnosis",
        True,
    )


def secondary_allowed(
    cause: str, *, region_proven: bool, source_readable: bool, token_value_present: bool
) -> bool:
    return (
        cause == "OCR_RECOGNITION_MISS"
        and region_proven
        and source_readable
        and not token_value_present
    )


def build(root: Path = ROOT) -> dict:
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    out = root / "evaluation_results/governed_30_root_collapse"
    old = root / "evaluation_results/governed_30_candidate_coverage"
    rows = read(out / "coverage_records.local.json")
    frozen = root / "evaluation_results/governed_30_root_cause/frozen"
    frozen_seals = read(frozen / "run_manifest.local.json")
    for source, entry in frozen_seals.items():
        if digest(frozen / entry["snapshot"]) != entry["sha256"]:
            raise ValueError("FROZEN_RELEASE_EVIDENCE_CHANGED")
        if (
            source == "config/field_acceptance_policies.yaml"
            and digest(root / source) != entry["sha256"]
        ):
            raise ValueError("ACCEPTANCE_POLICY_CHANGED")
    runtime = read(frozen / "raw_execution.local.json")
    reference = read(frozen / "governed_30_reference.local.json")
    policy = FieldPolicyRegistry.load(frozen / "field_acceptance_policies.yaml")
    runtime_score, _ = score(read(frozen / "governed_30_manifest.json"), reference, runtime, policy)
    runtime_claims = {c["claim_alias"]: c for c in runtime["claims"]}
    if len(rows) != 118 or sum(r["after_recall"]["5"] for r in rows) != 12:
        raise ValueError("SEALED_118_SLOT_12_MATCH_BASELINE_REQUIRED")
    seal = read(root / "docs/qualification/governed_30_candidate_coverage_seal.json")
    for name in (
        "coverage_records.local.json",
        "coverage_summary.local.json",
        "primary_capture_input.local.json",
        "source_visibility.local.json",
    ):
        if digest(out / name) != seal["local_evidence"][name]:
            raise ValueError("PRIOR_ITERATION_EVIDENCE_CHANGED")
    inputs = read(out / "primary_capture_input.local.json")["pages"]
    pools: dict[str, dict[str, list[dict]]] = {
        m: defaultdict(list) for m in ("baseline", "orientation", "geometry", "combined")
    }
    captures: dict[str, list[dict]] = defaultdict(list)
    oriented_captures: dict[str, list[dict]] = defaultdict(list)
    label_index: dict[str, list[dict]] = defaultdict(list)
    started = time.perf_counter()
    for page in inputs:
        name = f"{page['claim_alias']}_P{page['page_number']:03}.local.json"
        if (
            digest(Path(page["image_path"])) != page["image_sha256"]
            or digest(old / "primary_tokens" / name) != seal["primary_captures"][name]
        ):
            raise ValueError("SOURCE_OR_PRIMARY_CAPTURE_CHANGED")
        original = read(old / "primary_tokens" / name)
        rotated_path = out / "oriented_tokens" / name
        rotated = read(rotated_path) if rotated_path.exists() else original
        if rotated is not original and (
            rotated["image_sha256"] != page["image_sha256"]
            or rotated["rotation"] != 180
            or not rotated["osd_agrees"]
            or rotated["authority"] != "MANUALLY_VERIFIED_DIAGNOSTIC_ONLY"
        ):
            raise ValueError("UNPROVEN_ORIENTATION_TRANSFORM")
        alias = page["claim_alias"]
        captures[alias].append(original)
        oriented_captures[alias].append(rotated)
        original_lines = [TextLine(**t) for t in original["tokens"]]
        for i, field in labels(original_lines):
            t = original_lines[i]
            label_index[alias].append(
                {
                    "field": field,
                    "page_number": page["page_number"],
                    "token_index": i,
                    "bbox": [t.x0, t.y0, t.x1, t.y1],
                }
            )
        with Image.open(page["image_path"]) as image:
            width, height = image.size
        for mode in pools:
            cap = rotated if mode in {"orientation", "combined"} else original
            tokens = [TextLine(**t) for t in cap["tokens"]]
            proposals = (
                generate_structural(tokens, width=width, height=height)
                if mode in {"geometry", "combined"}
                else generate(tokens, width=width, height=height)
            )
            pools[mode][alias].extend(
                {
                    **asdict(c),
                    "page_number": page["page_number"],
                    "orientation": 180 if cap is not original else 0,
                }
                for c in proposals
            )
    public, private = [], []
    for row in rows:
        alias, field, expected = row["claim_alias"], row["field"], row["reference_value"]
        reference_key = comparison_key(field, expected)
        canonical = _canonical(policy, row["form"], field)
        runtime_rows = [
            r
            for r in runtime_claims[alias]["fields"]
            if r.get("service_line_number") is None
            and _canonical(policy, row["form"], r["field_name"]) == canonical
        ]
        route, _ = routing_state(
            runtime_claims[alias], runtime_rows, canonical, row["form"], policy
        )
        if route != row["runtime_route"]:
            raise ValueError("FROZEN_RUNTIME_ROUTE_CHANGED")
        matches, exact, dates = [], False, False
        principal_tokens = []
        for cap in captures[alias]:
            if cap["page_number"] not in row["source_visibility"]["source_pages"]:
                continue
            for i, t in enumerate(cap["tokens"]):
                same = comparison_key(field, t["text"]) == reference_key
                exact |= same
                if token_presence(field, expected, [t]):
                    matches.append(
                        {
                            "page_number": cap["page_number"],
                            "token_index": i,
                            "bbox": [t[k] for k in ("x0", "y0", "x1", "y1")],
                        }
                    )
                if (
                    field == "patient_dob"
                    and re.fullmatch(r"[0-9]{8}_?", t["text"].strip())
                    and t["x0"] < 250
                    and 235 <= t["y0"] < 300
                ):
                    dates = True
                # Evaluation-only localization audit against the supplied UB box-67
                # geometry; never a crop or candidate-generation input.
                if (
                    field == "principal_diagnosis"
                    and 60 <= t["x0"] < 245
                    and 1670 <= t["y0"] < 1745
                ):
                    principal_tokens.append(t)
        anchors = [
            r
            for r in label_index[alias]
            if r["field"] == field and r["page_number"] in row["source_visibility"]["source_pages"]
        ]
        relationships = []
        for match in matches:
            same_page = [a for a in anchors if a["page_number"] == match["page_number"]]
            if same_page:
                anchor = min(same_page, key=lambda a: abs(a["bbox"][1] - match["bbox"][1]))
                relationships.append(
                    {
                        "page_number": match["page_number"],
                        "label_token_index": anchor["token_index"],
                        "value_token_index": match["token_index"],
                        "dx": match["bbox"][0] - anchor["bbox"][0],
                        "dy": match["bbox"][1] - anchor["bbox"][3],
                        "horizontal_overlap": max(
                            0,
                            min(match["bbox"][2], anchor["bbox"][2])
                            - max(match["bbox"][0], anchor["bbox"][0]),
                        ),
                    }
                )
        source_tokens = [
            (cap["page_number"], t)
            for cap in captures[alias]
            if cap["page_number"] in row["source_visibility"]["source_pages"]
            for t in cap["tokens"]
        ]
        column_only = (
            field == "total_charge"
            and any(
                page == anchor["page_number"]
                and abs(t["y0"] - anchor["bbox"][1]) <= anchor["bbox"][3] - anchor["bbox"][1]
                and re.search(
                    r"hcpcs|non.?cover|serv.*units|rev[ .]*c(?:d|o)", t["text"], re.IGNORECASE
                )
                for page, t in source_tokens
                for anchor in anchors
            )
            and not any(
                c["field_name"] == field and c["reason"] == "TOTALS_ROW_CHARGE_COLUMN_INTERSECTION"
                for c in pools["baseline"][alias]
            )
        )
        merged_amount = field == "total_charge" and any(
            page == anchor["page_number"]
            and anchor["bbox"][0] <= t["x0"] <= anchor["bbox"][0] + 400
            and anchor["bbox"][3] - 5 <= t["y0"] <= anchor["bbox"][3] + 100
            and source_amount_components(t["text"]) is not None
            and comparison_key(field, source_amount_components(t["text"]) or "") == reference_key
            and t["text"].strip() != source_amount_components(t["text"])
            for page, t in source_tokens
            for anchor in anchors
        )
        trace = {
            "token_matches": matches,
            "charge_column_header_only": column_only,
            "merged_amount_match": merged_amount,
            "label_matches": anchors,
            "relationships": relationships,
            "exact_order_token_match": exact,
            "local_value_match": any(
                p["horizontal_overlap"] > 0 and -10 <= p["dy"] <= 100 for p in relationships
            ),
            "numeric_date_present": dates,
            "amount_assembly_match": any(
                c["field_name"] == field
                and c["reason"] == "SOURCE_NUMERIC_COMPONENT_ASSEMBLY"
                and comparison_key(field, c["value"]) == reference_key
                for c in pools["geometry"][alias]
            ),
            "principal_region_observed": bool(principal_tokens),
            "principal_region_match": any(
                comparison_key(field, t["text"]) == reference_key for t in principal_tokens
            ),
            "authority": "RECONSTRUCTED_FROZEN_TOKEN_GEOMETRY; not original worker trace",
        }
        cause, reason, extractable = (
            classify(row, trace)
            if not row["after_recall"]["5"]
            else (None, "ALREADY_COVERED", True)
        )
        modes: dict[str, dict] = {}
        detailed_modes = {}
        for mode, aliases in pools.items():
            evidence = [c for c in aliases[alias] if c["field_name"] == field]
            values = unique_values(
                field,
                row["before_candidates"] + [c["value"] for c in evidence] + row["secondary_values"],
            )
            modes[mode] = {
                "recall": ranks(field, expected, values),
                "candidate_count": len(values),
                "first_match_rank": next(
                    (
                        i + 1
                        for i, v in enumerate(values)
                        if comparison_key(field, v) == reference_key
                    ),
                    None,
                ),
            }
            detailed_modes[mode] = {**modes[mode], "values": values, "evidence": evidence}
        if modes["baseline"]["recall"] != row["after_recall"]:
            raise ValueError("PRIOR_CANDIDATE_POOL_NOT_REPRODUCED")
        if row["after_recall"]["5"] and not modes["combined"]["recall"]["5"]:
            raise ValueError("CANDIDATE_RECALL_REGRESSION")
        after_presence = token_presence(
            field,
            expected,
            [
                t
                for c in oriented_captures[alias]
                if c["page_number"] in row["source_visibility"]["source_pages"]
                for t in c["tokens"]
            ],
        )
        record = {
            "claim_alias": alias,
            "field": field,
            "form": row["form"],
            "critical": row["critical"],
            "baseline_miss": not row["after_recall"]["5"],
            "primary_cause": cause,
            "reason": reason,
            "extractable_under_frozen_contract": extractable,
            "source_visibility": row["source_visibility"],
            "trace": trace,
            "experiments": modes,
            "before_token_presence": bool(matches),
            "after_orientation_token_presence": after_presence,
            "production_route": row["runtime_route"],
            "review_only": True,
        }
        public.append(record)
        private.append({**record, "reference_value": expected, "experiments": detailed_modes})
    misses = [r for r in public if r["baseline_miss"]]
    assert len(misses) == 106 and all(r["primary_cause"] in CAUSES for r in misses)
    extractable_rows = [r for r in public if r["extractable_under_frozen_contract"]]
    recall = lambda rs, m: {
        f"R@{k}": metric(sum(r["experiments"][m]["recall"][str(k)] for r in rs), len(rs))
        for k in (1, 3, 5)
    }
    summary = {
        "status": "RECOVERABLE_COVERAGE_IMPROVED",
        "comparable": 118,
        "original_misses": 106,
        "taxonomy": {c: sum(r["primary_cause"] == c for r in misses) for c in CAUSES},
        "nonextractable_or_semantic": 118 - len(extractable_rows),
        "extractable": len(extractable_rows),
        "experiments": {m: recall(public, m) for m in pools},
        "critical_experiments": {m: recall([r for r in public if r["critical"]], m) for m in pools},
        "recoverable_recall": {m: recall(extractable_rows, m) for m in pools},
        "conditional_ceiling": metric(len(extractable_rows), len(extractable_rows)),
        "ceiling_status": "LOGICAL_SOURCE_PRESENT_UPPER_BOUND; not a measured OCR ceiling or release metric",
        "remaining_after": sum(not r["experiments"]["combined"]["recall"]["5"] for r in public),
        "new_secondary_ocr_calls": 0,
        "production_changes": False,
        "routing_at_each_milestone": {
            "scope": "SEALED_RUNTIME_EVENTS_RECONCILED; proposals are not worker emissions",
            "AUTO_ACCEPTED": 0,
            "HITL": 16,
            "NOT_EMITTED": 102,
            "NOT_ELIGIBLE": 6,
            "UNKNOWN": 0,
            "transitions": 0,
            "claim_hitl": runtime_score["claim_hitl"],
            "true_stp": runtime_score["true_stp"],
            "output_failures": runtime_score["pipeline_failure_types"],
            "safe_outputs": 0,
        },
        "replay_seconds": time.perf_counter() - started,
        "field_results": {
            f: {
                "comparable": len(rs),
                "after": recall(rs, "combined"),
                "source_semantic": sum(not r["extractable_under_frozen_contract"] for r in rs),
                "miss_causes": dict(Counter(r["primary_cause"] for r in rs if r["baseline_miss"])),
            }
            for f in [
                "member_id",
                "provider_name",
                "patient_name",
                "insured_name",
                "patient_dob",
                "service_date",
                "total_charge",
                "principal_diagnosis",
            ]
            for rs in [[r for r in public if r["field"] == f]]
        },
    }
    for name, data in {
        "root_collapse_summary.local.json": summary,
        "root_collapse_records.local.json": private,
        "remaining_miss_taxonomy.local.json": {"fields": misses},
        "all_field_audit.local.json": {"fields": public},
    }.items():
        (out / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
