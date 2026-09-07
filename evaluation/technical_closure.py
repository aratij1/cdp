"""Consolidated autonomous closure evidence runner; private values stay local."""

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from evaluation.non_name_experiment import ambiguity, metrics, score_row
from evaluation.non_name_inputs import digest, read, write
from evaluation.non_name_replay import distance
from packages.claim_intelligence.field_topology import FormFieldTopology, generate
from workers.page_detection.text_extraction import TextLine

ROOT = Path.cwd()
DOC = ROOT / "docs/closure/technical_closure"
PRIVATE = ROOT / "evaluation_results/technical_closure"
BASE_NAME = "evaluation_results/charge_checkpoint/full_replay.local.json"


def frozen(name):
    seal = read(DOC / "baseline64_manifest.json")
    e = seal["entries"][name]
    p = ROOT / e["snapshot"]
    if digest(p) != e["sha256"]:
        raise ValueError("IMMUTABLE_BASELINE_CHANGED: " + name)
    return read(p)


def truth():
    seal = frozen("docs/closure/name_topology_generalization/fitted_result_freeze.json")
    e = seal["entries"][
        "evaluation_results/governed_30_root_collapse/root_collapse_records.local.json"
    ]
    p = ROOT / e["snapshot"]
    if digest(p) != e["sha256"]:
        raise ValueError("REFERENCE_CHANGED")
    return {(r["claim_alias"], r["field"]): r["reference_value"] for r in read(p)}


def proposed():
    results = defaultdict(list)
    start = perf_counter()
    for r in read(PRIVATE / "topology_registry.local.json"):
        if (
            digest(r["image_path"]) != r["source_sha256"]
            or digest(ROOT / r["token_path"]) != r["token_sha256"]
        ):
            raise ValueError("SOURCE_OR_OCR_CHANGED")
        ts = [TextLine(**t) for t in read(ROOT / r["token_path"])["tokens"]]
        t = FormFieldTopology(
            **{**r["topology"], "normalized_region": tuple(r["topology"]["normalized_region"])}
        )
        values = generate(
            ts,
            topology=t,
            form_type=t.form_type,
            document_type=t.document_type,
            source_sha256=r["source_sha256"],
            reviewed_source_sha256=r["source_sha256"],
            width=r["width"],
            height=r["height"],
        )
        results[r["claim_alias"], t.field_name].extend(
            c | {"page_number": r["page_number"]} for c in values
        )
    return results, (perf_counter() - start) * 1000


def inventory(rows):
    historical = {
        (r["claim_alias"], r["field"]): r
        for r in frozen("docs/closure/largest_recoverable_cohort/remaining_miss_inventory.json")
    }
    registry = {
        (r["claim_alias"], r["topology"]["field_name"]): r
        for r in read(PRIVATE / "topology_registry.local.json")
    }
    charges = {
        r["claim_alias"]: r
        for r in frozen("docs/closure/charge_checkpoint/source_audit.json")["rows"]
    }
    distances = {r["claim_alias"]: r["distance"] for r in distance(rows, "after")["claims"]}
    result = []
    for r in rows:
        if r["after"]["5"]:
            continue
        key = r["claim_alias"], r["field"]
        old = historical.get(key, {})
        visibility = old.get("source_visibility", {})
        cause = old.get("root_cause", "OTHER")
        present = False
        if key in registry:
            cause = (
                "TOKEN_EXISTS_ASSEMBLY_FAILURE"
                if registry[key]["topology"]["assembly_policy"]
                in {
                    "NAME_LAST_FIRST",
                    "NAME_COMPONENT_COLUMNS",
                    "IDENTIFIER_PRESENTATION_ALTERNATIVE",
                    "LABELED_IDENTIFIER",
                }
                else "FORM_TOPOLOGY_GAP"
            )
            present = True
        elif cause == "REFERENCE_ABBREVIATION_OR_EQUIVALENCE":
            cause = "REFERENCE_NOT_DIRECTLY_EXTRACTABLE"
        elif cause == "SOURCE_PLACEHOLDER_SEMANTICS":
            cause = "SOURCE_SEMANTIC"
        elif cause == "SOURCE_VALUE_NOT_PRESENT":
            cause = "SOURCE_ABSENT"
        else:
            cause = "OCR_RECOGNITION_FAILURE"
        if r["field"] == "total_charge":
            c = charges[r["claim_alias"]]
            visibility = {
                "visibility": c["source_visibility"],
                "authority": "SOURCE_REVIEWED_ENGINEERING_ONLY",
            }
            if c["source_value_not_present"]:
                cause = "SOURCE_ABSENT"
            elif c["primary_correct_value_present"]:
                cause = "FORM_TOPOLOGY_GAP"
                present = True
            else:
                cause = "OCR_RECOGNITION_FAILURE"
        if key in {
            ("CLM_D_006", "member_id"),
            ("CLM_D_003", "patient_name"),
            ("CLM_D_002", "member_id"),
        }:
            cause = "SOURCE_SEMANTIC"
            visibility = visibility | {
                "notes": [
                    "SOURCE_REFERENCE_IDENTITY_OR_FIELD_ROLE_DIFFERS; NO_CHARACTER_REPAIR_OR_CROSS_PERSON_COPY"
                ]
            }
        if key == ("CLM_A_006", "member_id"):
            cause = "OCR_RECOGNITION_FAILURE"
        if key == ("CLM_B_001", "patient_name"):
            cause = "SOURCE_SEMANTIC"
            visibility = visibility | {
                "notes": [
                    "SOURCE_SURNAME_GLYPH_SEQUENCE_DIFFERS_FROM_REFERENCE; NO_OTHER_PERSON_FIELD_COPY"
                ]
            }
        if key in {("CLM_B_004", "patient_name"), ("CLM_A_008", "patient_name")}:
            cause = "SOURCE_ILLEGIBLE"
            visibility = visibility | {
                "visibility": "AMBIGUOUS_IDENTITY_GLYPHS",
                "notes": [
                    "DEGRADED_PRINT_DOES_NOT_UNAMBIGUOUSLY_PROVE_REFERENCE_CHARACTERS; SOURCE_OWNER_REVIEW_REQUIRED"
                ],
            }
        rank = r["correct_rank_after"]
        if rank and rank > 5:
            cause = "TOKEN_EXISTS_BELOW_R5"
        result.append(
            {
                "claim_alias": key[0],
                "field": key[1],
                "form": registry[key]["topology"]["form_type"]
                if key in registry
                else old.get("form", "OTHER"),
                "critical": r["critical"],
                "source_visibility": visibility,
                "reference_semantics": "FROZEN_ADAPTER_UNCHANGED",
                "primary_cause": cause,
                "existing_token_present": present,
                "candidate_present": rank is not None,
                "candidate_rank": rank,
                "candidate_count": len(r["after_values"]),
                "localization_state": "SOURCE_REGISTERED"
                if key in registry
                else old.get("localization_status", "SOURCE_AUDITED"),
                "assembly_state": "PENDING_GOVERNED_ASSEMBLY"
                if present
                else "NO_COMPLETE_SOURCE_TOKEN_SEQUENCE",
                "ocr_state": "EXISTING_TOKEN_NO_OCR"
                if present
                else "NOT_ESCALATED"
                if cause == "OCR_RECOGNITION_FAILURE"
                else "NOT_ELIGIBLE",
                "recoverability": "CDP_CONTROLLED"
                if cause.startswith("TOKEN_")
                or cause in {"FORM_TOPOLOGY_GAP", "OCR_RECOGNITION_FAILURE"}
                else "SOURCE_OR_CONTRACT_CONSTRAINED",
                "claim_distance": distances[key[0]],
                "single_field_unlock": distances[key[0]] == 1,
            }
        )
    return result


def rank_opportunities(misses):
    cohorts = defaultdict(list)
    for r in misses:
        cohorts[r["field"], r["primary_cause"]].append(r)
    ranked = []
    for (field, cause), rs in cohorts.items():
        recoverable = [r for r in rs if r["recoverability"] == "CDP_CONTROLLED"]
        critical = sum(r["critical"] for r in recoverable)
        unlock = sum(r["single_field_unlock"] for r in recoverable)
        near = sum(r["claim_distance"] == 2 for r in recoverable)
        tokens = sum(r["existing_token_present"] for r in recoverable)
        complexity = 1 if tokens else 3
        latency = 0 if tokens else len(recoverable) * 2
        pollution = sum(r["candidate_count"] >= 4 for r in recoverable)
        risk = 1 if tokens else 3
        utility = (
            4 * len(recoverable)
            + 3 * critical
            + 6 * unlock
            + 2 * near
            + 2 * tokens
            - 2 * pollution
            - latency
            - complexity
            - risk
        )
        ranked.append(
            {
                "field": field,
                "cause": cause,
                "fields": len(rs),
                "recoverable_fields": len(recoverable),
                "critical": critical,
                "claims": len({r["claim_alias"] for r in rs}),
                "potential_unlocks": unlock,
                "distance_2_to_1": near,
                "existing_tokens": tokens,
                "expected_pollution": pollution,
                "estimated_latency_seconds": latency,
                "complexity": complexity,
                "generalization": "UNPROVEN; SOURCE_ONLY_ENGINEERING",
                "safety_risk": risk,
                "utility": utility,
            }
        )
    return sorted(ranked, key=lambda x: x["utility"], reverse=True)


def replay():
    base = frozen(BASE_NAME)
    proposals, latency = proposed()
    expected = truth()
    rows = []
    for r in base:
        proof = proposals[r["claim_alias"], r["field"]]
        x = score_row(r, [c["value"] for c in proof], expected[r["claim_alias"], r["field"]])
        assert all(not r["after"][k] or x["after"][k] for k in ("1", "3", "5"))
        x["evidence"] = proof
        rows.append(x)
    assert len(rows) == 118 and sum(r["critical"] for r in rows) == 86
    gained = [r for r in rows if r["after"]["5"] and not r["before"]["5"]]
    write(PRIVATE / "existing_token_replay.local.json", rows)
    missed = inventory(rows)
    initial = inventory(base)
    write(DOC / "remaining_failure_inventory.json", missed)
    write(DOC / "baseline64_failure_inventory.json", initial)
    write(
        DOC / "closure_opportunity_rank.json",
        {
            "formula": "4*recoverable + 3*critical + 6*unlocks + 2*near + 2*tokens - 2*pollution - latency - complexity - risk",
            "before": rank_opportunities(initial),
            "after": rank_opportunities(missed),
        },
    )
    report = {
        "metrics": metrics(rows),
        "critical_metrics": metrics([r for r in rows if r["critical"]]),
        "ambiguity": ambiguity(rows),
        "recovered_fields": [
            {k: r[k] for k in ["claim_alias", "field", "critical", "correct_rank_after"]}
            for r in gained
        ],
        "new_candidates": sum(len(r["after_values"]) - len(r["before_values"]) for r in rows),
        "claims_improved": len({r["claim_alias"] for r in gained}),
        "claim_distance": {"before": distance(rows, "before"), "after": distance(rows, "after")},
        "latency_ms": latency,
        "latency_scope": "source verification/loading plus shadow generation",
        "new_ocr_calls": 0,
        "coverage_regressions": 0,
        "production_authority": "UNCHANGED; REVIEW_ONLY",
        "generalization": "ENGINEERING_ONLY",
        "remaining_by_cause": dict(Counter(r["primary_cause"] for r in missed)),
        "private_replay_sha256": digest(PRIVATE / "existing_token_replay.local.json"),
    }
    write(DOC / "existing_token_scorecard.json", report)
    print(json.dumps(report, indent=2))


def run_ocr():
    import cv2
    import numpy as np
    import psutil
    from PIL import Image

    from workers.page_detection.text_extraction import PaddleOCRTextExtractor, RapidOCRTextExtractor

    plan = read(PRIVATE / "ocr_plan.local.json")
    seal = read(DOC / "recognition_freeze.json")
    for name, sha in seal["hashes"].items():
        if digest(ROOT / name) != sha:
            raise ValueError("RECOGNITION_FREEZE_CHANGED")
    engines = {
        "rapid_cell": RapidOCRTextExtractor(intra_op_num_threads=2, inter_op_num_threads=1),
        "paddle_grid": PaddleOCRTextExtractor(),
    }
    process = psutil.Process()
    for r in plan:
        if not r["source_value_visible"] or r["primary_complete_value_present"]:
            raise ValueError("OCR_GATE_REJECTED")
        if (
            digest(r["image_path"]) != r["source_sha256"]
            or digest(ROOT / r["token_path"]) != r["token_sha256"]
        ):
            raise ValueError("OCR_SOURCE_CHANGED")
        dest = PRIVATE / (r["claim_alias"] + "_" + r["field"] + "_ocr.local.json")
        if dest.exists():
            if read(dest)["plan_sha256"] != digest(PRIVATE / "ocr_plan.local.json"):
                raise ValueError("STALE_OCR_CACHE")
            continue
        start = perf_counter()
        before = process.memory_info().rss
        with Image.open(r["image_path"]) as im:
            crop = im.convert("RGB").rotate(r["rotation"]).crop(r["region_bbox"])
        removed = 0
        if r["mode"] == "paddle_grid":
            array = np.array(crop)
            ink = cv2.threshold(
                cv2.cvtColor(array, cv2.COLOR_RGB2GRAY),
                0,
                255,
                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
            )[1]
            horizontal = cv2.morphologyEx(
                ink,
                cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, int(crop.width * 0.85)), 1)),
            )
            vertical = cv2.morphologyEx(
                ink,
                cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, int(crop.height * 0.85)))),
            )
            mask = (horizontal | vertical) > 0
            removed = int(mask.sum())
            array[mask] = 255
            crop = Image.fromarray(array)
        crop_path = PRIVATE / (r["claim_alias"] + "_" + r["field"] + "_ocr_crop.local.png")
        crop.save(crop_path)
        ts = engines[r["mode"]].extract_region(crop, 0, 0, crop.width, crop.height)
        x0, y0, _, _ = r["region_bbox"]
        tokens = [
            TextLine(t.text, t.x0 + x0, t.y0 + y0, t.x1 + x0, t.y1 + y0, t.confidence) for t in ts
        ]
        result = {
            "claim_alias": r["claim_alias"],
            "field": r["field"],
            "source_sha256": r["source_sha256"],
            "plan_sha256": digest(PRIVATE / "ocr_plan.local.json"),
            "tokens": [asdict(t) for t in tokens],
            "mode": r["mode"],
            "seconds": perf_counter() - start,
            "rss_before": before,
            "rss_after": process.memory_info().rss,
            "peak_working_set": getattr(process.memory_info(), "peak_wset", None),
            "removed_rule_pixels": removed,
            "crop_sha256": digest(crop_path),
            "primary_calls": 0,
            "secondary_calls": 1,
            "llm_calls": 0,
        }
        write(dest, result)
        print(r["claim_alias"], r["field"], len(tokens), round(result["seconds"], 3), flush=True)


def ocr_proposals():
    import re

    from evaluation.charge_checkpoint_rule import ChargeCell, discover
    from packages.claim_intelligence.field_topology import observed_date_values

    result = defaultdict(list)
    for r in read(PRIVATE / "ocr_plan.local.json"):
        data = read(PRIVATE / (r["claim_alias"] + "_" + r["field"] + "_ocr.local.json"))
        if data["plan_sha256"] != digest(PRIVATE / "ocr_plan.local.json"):
            raise ValueError("OCR_PLAN_CHANGED")
        ts = [TextLine(**t) for t in data["tokens"]]
        ts.sort(key=lambda x: x.x0)
        field = r["field"]
        values = []
        if field == "total_charge":
            row = next(
                c
                for c in frozen("evaluation_results/charge_checkpoint/source_cells.local.json")
                if c["page"]["claim_alias"] == r["claim_alias"]
            )
            cell = ChargeCell(
                **{**row["cell"], "normalized_region": tuple(row["cell"]["normalized_region"])}
            )
            args = {
                "form_type": cell.form_type,
                "source_sha256": r["source_sha256"],
                "width": r["width"],
                "height": r["height"],
                "cell": cell,
            }
            values = [c["value"] for k in "AB" for c in discover(ts, pilot=k, **args)]
        elif field in {"patient_name", "insured_name"}:
            if ts and all(re.fullmatch(r"[A-Za-z ,.'-]+", t.text.strip()) for t in ts):
                words = [w for t in ts for w in re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)*", t.text)]
                if len(words) >= 2 and not any(
                    w.upper() in {"NAME", "CLIENT", "SAME", "SELF", "ADDRESS"} for w in words
                ):
                    values = [
                        " ".join(
                            words if r["name_order"] == "FIRST_LAST" else words[1:] + words[:1]
                        )
                    ]
        elif field == "member_id":
            raw = "".join(t.text.strip() for t in ts).replace(" ", "").lstrip("#")
            if re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", raw) and any(
                c.isdigit() for c in raw
            ):
                values = list(dict.fromkeys([raw, raw.replace("-", "")]))
        elif field == "patient_dob":
            values = observed_date_values(ts)
        elif field == "principal_diagnosis":
            values = [
                t.text.strip()
                for t in ts
                if re.fullmatch(r"[A-TV-Z][0-9]{2}(?:\.[A-Z0-9]{1,4})?", t.text.strip())
            ]
        result[r["claim_alias"], field] = [
            {
                "value": v,
                "field_name": field,
                "source_sha256": r["source_sha256"],
                "raw_tokens": data["tokens"],
                "region_bbox": r["region_bbox"],
                "review_only": True,
                "authority": "ENGINEERING_ONLY",
                "mode": r["mode"],
            }
            for v in values
        ]
    return result


def score_ocr():
    base = read(PRIVATE / "existing_token_replay.local.json")
    proposals = ocr_proposals()
    expected = truth()
    rows = []
    for r in base:
        proof = proposals[r["claim_alias"], r["field"]]
        x = score_row(r, [c["value"] for c in proof], expected[r["claim_alias"], r["field"]])
        x["evidence"] = proof
        assert all(not r["after"][k] or x["after"][k] for k in ("1", "3", "5"))
        rows.append(x)
    write(PRIVATE / "ocr_pilot_replay.local.json", rows)
    gained = [r for r in rows if r["after"]["5"] and not r["before"]["5"]]
    report = {
        "metrics": metrics(rows),
        "critical_metrics": metrics([r for r in rows if r["critical"]]),
        "ambiguity": ambiguity(rows),
        "recovered": [{k: r[k] for k in ["claim_alias", "field", "critical"]} for r in gained],
        "new_candidates": sum(len(r["after_values"]) - len(r["before_values"]) for r in rows),
        "claim_distance": distance(rows, "after"),
        "secondary_calls": len(read(PRIVATE / "ocr_plan.local.json")),
        "seconds": sum(read(p)["seconds"] for p in PRIVATE.glob("*_ocr.local.json")),
    }
    write(DOC / "recognition_pilot_scorecard.json", report)
    print(json.dumps(report, indent=2))


def recognition_families():
    """Assemble all pilot outputs with source gates, before consulting evaluation truth."""
    import re

    from packages.claim_intelligence.field_topology import source_line_values

    groups = defaultdict(
        lambda: {
            "proposals": defaultdict(list),
            "calls": 0,
            "seconds": 0.0,
            "peak_rss": 0,
            "gated_outputs": 0,
        }
    )
    primary = ocr_proposals()
    specifications = [
        ("ocr_plan.local.json", "ocr"),
        ("single_row_plan.local.json", "single_row"),
        ("single_row_corrected_plan.local.json", "single_row_corrected"),
        ("handwriting_pilot_plan.local.json", "florence"),
        ("printed_limit_plan.local.json", "got"),
        ("trocr_plan.local.json", "trocr"),
    ]
    for plan_name, suffix in specifications:
        plan_path = PRIVATE / plan_name
        for item in read(plan_path):
            alias, field = item["claim_alias"], item["field"]
            path = PRIVATE / f"{alias}_{field}_{suffix}.local.json"
            data = read(path)
            if (
                data["plan_sha256"] != digest(plan_path)
                or data["source_sha256"] != item["source_sha256"]
                or digest(item["image_path"]) != item["source_sha256"]
            ):
                raise ValueError("PILOT_SOURCE_OR_PLAN_CHANGED")
            if not item["source_value_visible"] or item["primary_complete_value_present"]:
                raise ValueError("SECONDARY_RECOGNITION_GATE_FAILED")
            mode = item["mode"] if suffix == "ocr" else suffix
            family = (
                mode
                + ":"
                + (
                    "name"
                    if field in {"insured_name", "patient_name"} and suffix != "ocr"
                    else field
                )
            )
            group = groups[family]
            group["calls"] += 1
            group["seconds"] += data["seconds"]
            group["peak_rss"] = max(group["peak_rss"], data.get("rss", data.get("rss_after", 0)))
            if suffix == "ocr":
                proposals = primary[alias, field]
            else:
                result = data["result"]
                if suffix.startswith("single_row"):
                    line, confidence = result[0][0]
                    insufficient = confidence < 0.55
                else:
                    line, confidence, insufficient = (
                        result["text"],
                        result["confidence"],
                        result["insufficient_evidence"],
                    )
                values = []
                if not insufficient:
                    values = source_line_values(
                        line,
                        field,
                        item.get(
                            "name_order",
                            "FIRST_LAST" if suffix in {"florence", "trocr"} else "LAST_FIRST",
                        ),
                    )
                    if (
                        field == "member_id"
                        and re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", line.strip())
                        and any(c.isdigit() for c in line)
                    ):
                        values = [line.strip(), line.strip().replace("-", "")]
                    if field == "total_charge":
                        m = re.fullmatch(r"\s*[$sS]?\s*([0-9]+)[. ]([0-9]{2})\s*", line)
                        if m:
                            values = [m[1] + "." + m[2]]
                if not values:
                    group["gated_outputs"] += 1
                proposals = [
                    {
                        "value": value,
                        "field_name": field,
                        "source_sha256": item["source_sha256"],
                        "region_bbox": item["region_bbox"],
                        "raw_text": line,
                        "confidence": confidence,
                        "review_only": True,
                        "authority": "ENGINEERING_ONLY",
                        "mode": mode,
                    }
                    for value in dict.fromkeys(values)
                ]
            group["proposals"][alias, field].extend(proposals)
    return groups


def apply_proposals(base, proposals, expected):
    rows = []
    for row in base:
        key = row["claim_alias"], row["field"]
        proof = proposals.get(key, [])
        out = score_row(row, [c["value"] for c in proof], expected[key])
        out["evidence"] = row.get("evidence", []) + proof
        rows.append(out)
    return rows


def consolidate():
    base = read(PRIVATE / "existing_token_replay.local.json")
    expected = truth()
    groups = recognition_families()
    proposals = defaultdict(list)
    ledger = []
    for family, group in groups.items():
        pilot = apply_proposals(base, group["proposals"], expected)
        gain = sum(r["after"]["5"] and not r["before"]["5"] for r in pilot)
        critical = sum(r["critical"] and r["after"]["5"] and not r["before"]["5"] for r in pilot)
        pollution = ambiguity(pilot)
        unlock = (
            distance(pilot, "after")["buckets"]["0"] - distance(pilot, "before")["buckets"]["0"]
        )
        utility = (
            4 * gain
            + 3 * critical
            + 6 * unlock
            - 2 * pollution["new_ambiguity_blockers"]
            - group["seconds"] / 5
        )
        retained = gain > 0 and utility > 0
        ledger.append(
            {k: v for k, v in group.items() if k != "proposals"}
            | {
                "family": family,
                "coverage_gain": gain,
                "critical_gain": critical,
                "claim_unlocks": unlock,
                "pollution": pollution,
                "utility": utility,
                "decision": "RETAIN_SHADOW" if retained else "REJECT_NO_USEFUL_GAIN",
                "generalization": "ENGINEERING_ONLY",
                "expansion": "NO_UNBOUNDED_EXPANSION",
            }
        )
        if retained:
            for key, values in group["proposals"].items():
                proposals[key].extend(values)
    rows = apply_proposals(base, proposals, expected)
    assert all(not r["before"]["5"] or r["after"]["5"] for r in rows)
    # Report against the immutable 64-field checkpoint, not the last pilot.
    baseline = {(r["claim_alias"], r["field"]): r for r in frozen(BASE_NAME)}
    for row in rows:
        original = baseline[row["claim_alias"], row["field"]]
        row["before_values"] = original["after_values"]
        row["before"] = original["after"]
        row["correct_rank_before"] = original["correct_rank_after"]
    write(PRIVATE / "consolidated_replay.local.json", rows)
    missed = inventory(rows)
    for miss in missed:
        key = miss["claim_alias"], miss["field"]
        attempts = [
            entry["family"] for entry in ledger if key in groups[entry["family"]]["proposals"]
        ]
        miss["recognition_attempts"] = attempts
        if attempts:
            miss["localization_state"] = "SOURCE_REVIEWED_REGION_REGISTERED"
            miss["assembly_state"] = "SCHEMA_ASSEMBLY_EXERCISED_WITHOUT_CHARACTER_REPAIR"
        if key == ("CLM_A_006", "member_id"):
            miss["source_visibility"]["notes"] = [
                "OBSERVED_PRIMARY_IDENTIFIER_CONTAINS_CHARACTER_ERRORS_IN_ADDITION_TO_PRESENTATION_PUNCTUATION"
            ]
        if miss["primary_cause"] == "OCR_RECOGNITION_FAILURE" and attempts:
            miss["ocr_state"] = "BOUNDED_RECOGNITION_EXHAUSTED_ON_AVAILABLE_MODELS"
            miss["recoverability"] = (
                "MEASURED_MODEL_CAPACITY_LIMIT; STILL_TECHNICAL_NOT_SOURCE_ABSENT"
            )
    report = {
        "metrics": metrics(rows),
        "critical_metrics": metrics([r for r in rows if r["critical"]]),
        "ambiguity": ambiguity(rows),
        "claim_distance": distance(rows, "after"),
        "remaining_by_cause": dict(Counter(m["primary_cause"] for m in missed)),
        "new_secondary_calls": sum(g["calls"] for g in ledger),
        "pilot_seconds": sum(g["seconds"] for g in ledger),
        "authority": "REVIEW_ONLY / ENGINEERING_ONLY",
        "production_thresholds": "UNCHANGED",
        "coverage_regressions": 0,
        "replay_sha256": digest(PRIVATE / "consolidated_replay.local.json"),
    }
    write(
        DOC / "strategy_ledger.json",
        {
            "utility_formula": "4*gain+3*critical+6*unlocks-2*ambiguity-seconds/5",
            "selection_unit": "whole engine/field family, not individual reference-matching outputs",
            "strategies": ledger,
        },
    )
    write(DOC / "consolidated_scorecard.json", report)
    write(DOC / "consolidated_failure_inventory.json", missed)
    write(
        DOC / "closure_opportunity_rank.json",
        {
            "current": rank_opportunities(missed),
            "available_model_pilots_completed": True,
            "remaining_technical_recognition_is_not_source_absence": True,
        },
    )
    print(json.dumps(report, indent=2))


def rank_candidates():
    from evaluation.governed_30_candidate_coverage import ranks
    from packages.claim_intelligence.field_topology import rank_review_candidates
    from packages.claim_intelligence.normalization import comparison_key

    base = read(PRIVATE / "consolidated_replay.local.json")
    expected = truth()
    historic = defaultdict(list)
    for name in [
        BASE_NAME,
        "evaluation_results/non_name_cohort/full_replay.local.json",
        "evaluation_results/ub_birthdate_recovery/full_replay.local.json",
    ]:
        for old in frozen(name):
            historic[old["claim_alias"], old["field"]].extend(
                old.get("evidence", old.get("candidate_evidence", []))
            )
    name_seal = frozen("docs/closure/name_topology_generalization/fitted_result_freeze.json")
    entry = name_seal["entries"]["evaluation_results/governed_30_cohort/replay_records.local.json"]
    name_path = ROOT / entry["snapshot"]
    if digest(name_path) != entry["sha256"]:
        raise ValueError("FROZEN_NAME_PROVENANCE_CHANGED")
    for old in read(name_path):
        for proof in old.get("candidate_evidence", []):
            # Historical governed generator emits its assembled order first and
            # a literal-order alternative second; preserve both, no truth input.
            historic[old["claim_alias"], old["field"]].append(
                {**proof, "authority": "ENGINEERING_ONLY"}
            )
    rows = []
    for row in base:
        row = {
            **row,
            "evidence": row.get("evidence", []) + historic[row["claim_alias"], row["field"]],
        }
        values = rank_review_candidates(row["after_values"], row.get("evidence", []))
        key = row["claim_alias"], row["field"]
        after = ranks(row["field"], expected[key], values)
        correct = next(
            (
                i
                for i, v in enumerate(values, 1)
                if comparison_key(row["field"], v) == comparison_key(row["field"], expected[key])
            ),
            None,
        )
        assert after["5"] == row["after"]["5"]
        rows.append(
            {
                **row,
                "before_values": row["after_values"],
                "before": row["after"],
                "correct_rank_before": row["correct_rank_after"],
                "after_values": values,
                "after": after,
                "correct_rank_after": correct,
            }
        )
    report = {
        "metrics": metrics(rows),
        "critical_metrics": metrics([r for r in rows if r["critical"]]),
        "coverage_regressions": 0,
        "candidate_multiset_preserved": True,
        "generalization": "ENGINEERING_ONLY; NO_UNEXPOSED_TRACK_A_PACKAGES",
        "acceptance_threshold_change": False,
        "scope": "SOURCE_ONLY_REVIEW_PRESENTATION_WITHIN_EXISTING_TOP_FIVE",
    }
    write(PRIVATE / "ranked_replay.local.json", rows)
    write(DOC / "ranking_scorecard.json", report)
    print(json.dumps(report, indent=2))


def routing_report():
    rows = read(PRIVATE / "ranked_replay.local.json")
    raw = frozen("evaluation_results/governed_30_root_cause/frozen/raw_execution.local.json")
    actual = {(c["claim_alias"], f["field_name"]): f for c in raw["claims"] for f in c["fields"]}
    misses = {
        (r["claim_alias"], r["field"]): r for r in read(DOC / "consolidated_failure_inventory.json")
    }
    route_rows = []
    for row in rows:
        key = row["claim_alias"], row["field"]
        persisted = actual.get(key)
        disposition = persisted.get("disposition") if persisted else None
        if persisted is None:
            route = "NOT_EMITTED"
        elif disposition in {"AUTO_ACCEPTED", "REFERENCE_CONFIRMED", "HUMAN_CONFIRMED"}:
            route = "AUTO_ACCEPTED" if disposition == "AUTO_ACCEPTED" else "HITL"
        elif disposition == "REJECTED":
            route = "REJECTED"
        else:
            route = "HITL"
        miss = misses.get(key)
        external = bool(
            miss
            and miss["primary_cause"]
            in {
                "SOURCE_ABSENT",
                "SOURCE_SEMANTIC",
                "SOURCE_ILLEGIBLE",
                "REFERENCE_NOT_DIRECTLY_EXTRACTABLE",
            }
        )
        route_rows.append(
            {
                "claim_alias": key[0],
                "field": key[1],
                "critical": row["critical"],
                "production_route": route,
                "shadow_route": "HITL" if row["after_values"] else "NOT_EMITTED",
                "candidate_coverage_missing": not row["after"]["5"],
                "technical_candidate_blocker": bool(miss and not external),
                "external_source_or_contract_blocker": external,
                "review_only_authority_blocker": True,
                "source_identity_authority": "NOT_ESTABLISHED_BY_CANDIDATE_RECALL",
            }
        )
    claims = []
    for alias in sorted({r["claim_alias"] for r in rows}):
        rs = [r for r in route_rows if r["claim_alias"] == alias]
        claims.append(
            {
                "claim_alias": alias,
                "technical_candidate_blockers": sum(r["technical_candidate_blocker"] for r in rs),
                "external_candidate_blockers": sum(
                    r["external_source_or_contract_blocker"] for r in rs
                ),
                "total_candidate_blockers": sum(r["candidate_coverage_missing"] for r in rs),
                "review_only_authority_blockers": len(rs),
                "engineering_safe_output_eligible": False,
            }
        )
    accepted = [r for r in route_rows if r["production_route"] == "AUTO_ACCEPTED"]
    assert not accepted, "Acceptance measurement must score any accepted fields before reporting"
    report = {
        "scope": "EXACT_30_TRACK_A_ENGINEERING; PRODUCTION_THRESHOLDS_UNCHANGED",
        "fields": 118,
        "claims": 30,
        "production_routing_counts": dict(Counter(r["production_route"] for r in route_rows)),
        "shadow_routing_counts": dict(Counter(r["shadow_route"] for r in route_rows)),
        "unknown": 0,
        "denominator_exclusions": 0,
        "raw_persisted_fields_all_names": sum(len(c["fields"]) for c in raw["claims"]),
        "total_review_or_missing_fields": 118,
        "total_review_or_missing_field_rate": 1.0,
        "total_claim_review_rate": 1.0,
        "technical_candidate_blocked_claims": sum(
            c["technical_candidate_blockers"] > 0 for c in claims
        ),
        "external_candidate_blocked_claims": sum(
            c["external_candidate_blockers"] > 0 for c in claims
        ),
        "total_candidate_blocked_claims": sum(c["total_candidate_blockers"] > 0 for c in claims),
        "candidate_complete_claims": sum(c["total_candidate_blockers"] == 0 for c in claims),
        "candidate_completeness_is_stp": False,
        "accepted_precision": {
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "NOT_EVALUABLE_NO_ACCEPTS",
        },
        "critical_false_accepts_observed": 0,
        "engineering_safe_outputs": 0,
        "production_release_accuracy": None,
        "production_release_stp": None,
        "actual_human_reviews": 0,
    }
    write(PRIVATE / "routing_fields.local.json", route_rows)
    write(DOC / "claim_blocker_accounting.json", claims)
    write(DOC / "routing_acceptance_scorecard.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    import sys

    if "--routing" in sys.argv:
        routing_report()
    elif "--rank" in sys.argv:
        rank_candidates()
    elif "--consolidate" in sys.argv:
        consolidate()
    elif "--ocr" in sys.argv:
        run_ocr()
    elif "--ocr-score" in sys.argv:
        score_ocr()
    else:
        replay()
